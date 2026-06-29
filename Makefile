PYTHON ?= python3
QLIB_DIR ?= /Users/renxg/.qlib/qlib_data/cn_data
INSTRUMENTS ?= $(QLIB_DIR)/instruments/csi300.txt
OUTPUT_DIR ?= outputs
YEARS ?= 10
WINDOW ?= 60
THRESHOLD ?= 0.001
BENCHMARK ?= sh000300
LIQUIDITY_FILTER_PCT ?= 0.1
AMOUNT_FIELD ?= amount
CHART_COUNT ?= 100
CHART_YEARS ?= 2
CHART_FORMAT ?= svg
CHART_OUTPUT_DIR ?= outputs/zigzag_2y_samples_svg
SIGNAL_INSTRUMENTS ?= $(QLIB_DIR)/instruments/all.txt
SIGNAL_OUTPUT_DIR ?= outputs/zigzag_signals_all
SIGNAL_YEARS ?= 2
API_HOST ?= 127.0.0.1
API_PORT ?= 8000
WEB_PORT ?= 5173

EXT_SUFFIX := $(shell $(PYTHON) -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')

.PHONY: help build-zigzag thiszigzag backtest zigzag-charts zigzag-signals install-docker-aliyun n-pattern-api n-pattern-web n-pattern-compose prod-deploy prod-restart prod-status prod-logs prod-down prod-health deploy run_zigzag_data clean-zigzag clean-outputs

help:
	@echo "Targets:"
	@echo "  make build-zigzag  Compile thiszigzag for the active Python"
	@echo "  make backtest      Compile thiszigzag, then run the CSI300 ZigZag backtest"
	@echo "  make zigzag-charts Render recent 2-year ZigZag sample charts"
	@echo "  make zigzag-signals Generate daily positive/reverse N signal files"
	@echo "  make n-pattern-api Run the FastAPI N-pattern browser backend"
	@echo "  make n-pattern-web Run the Vue N-pattern browser frontend"
	@echo "  make n-pattern-compose Run refresh daemon, API, and web containers"
	@echo "  make install-docker-aliyun Install Docker on Linux using Aliyun Docker CE repo"
	@echo "  make prod-deploy   Build and start production Docker services"
	@echo "  make prod-restart  Rebuild and restart production Docker services"
	@echo "  make prod-status   Show production service status"
	@echo "  make prod-logs     Follow production service logs"
	@echo "  make prod-health   Check production API health"
	@echo "  make prod-down     Stop production Docker services"
	@echo "  make deploy        Commit + push local changes, then pull and restart on production host"
	@echo ""
	@echo "Options:"
	@echo "  PYTHON=$(PYTHON)"
	@echo "  QLIB_DIR=$(QLIB_DIR)"
	@echo "  INSTRUMENTS=$(INSTRUMENTS)"
	@echo "  OUTPUT_DIR=$(OUTPUT_DIR)"
	@echo "  YEARS=$(YEARS) WINDOW=$(WINDOW) THRESHOLD=$(THRESHOLD) BENCHMARK=$(BENCHMARK)"
	@echo "  LIQUIDITY_FILTER_PCT=$(LIQUIDITY_FILTER_PCT) AMOUNT_FIELD=$(AMOUNT_FIELD)"
	@echo "  CHART_COUNT=$(CHART_COUNT) CHART_YEARS=$(CHART_YEARS) CHART_FORMAT=$(CHART_FORMAT) CHART_OUTPUT_DIR=$(CHART_OUTPUT_DIR)"
	@echo "  SIGNAL_INSTRUMENTS=$(SIGNAL_INSTRUMENTS) SIGNAL_YEARS=$(SIGNAL_YEARS) SIGNAL_OUTPUT_DIR=$(SIGNAL_OUTPUT_DIR)"
	@echo "  API_HOST=$(API_HOST) API_PORT=$(API_PORT) WEB_PORT=$(WEB_PORT)"
	@echo "  Production ports are configured in .env: API_BIND, API_PORT, WEB_BIND, WEB_HTTP_PORT"

build-zigzag:
	$(PYTHON) -c 'from setuptools import setup, Extension; import numpy; setup(name="thiszigzag_local_build", ext_modules=[Extension("thiszigzag.core", ["thiszigzag/core.c"], include_dirs=[numpy.get_include()])], script_args=["build_ext", "--inplace"])'

thiszigzag: build-zigzag

backtest: build-zigzag
	$(PYTHON) backtest_zigzag_csi300.py \
		--qlib-dir "$(QLIB_DIR)" \
		--instruments "$(INSTRUMENTS)" \
		--output-dir "$(OUTPUT_DIR)" \
		--years "$(YEARS)" \
		--window "$(WINDOW)" \
		--threshold "$(THRESHOLD)" \
		--benchmark "$(BENCHMARK)" \
		--liquidity-filter-pct "$(LIQUIDITY_FILTER_PCT)" \
		--amount-field "$(AMOUNT_FIELD)"

zigzag-charts: build-zigzag
	$(PYTHON) render_zigzag_samples.py \
		--qlib-dir "$(QLIB_DIR)" \
		--instruments "$(INSTRUMENTS)" \
		--output-dir "$(CHART_OUTPUT_DIR)" \
		--years "$(CHART_YEARS)" \
		--count "$(CHART_COUNT)" \
		--threshold "$(THRESHOLD)" \
		--format "$(CHART_FORMAT)"

zigzag-signals: build-zigzag
	$(PYTHON) generate_zigzag_signals.py \
		--qlib-dir "$(QLIB_DIR)" \
		--instruments "$(SIGNAL_INSTRUMENTS)" \
		--output-dir "$(SIGNAL_OUTPUT_DIR)" \
		--years "$(SIGNAL_YEARS)" \
		--window "$(WINDOW)" \
		--threshold "$(THRESHOLD)"

clean-zigzag:
	rm -rf build
	rm -f thiszigzag/core$(EXT_SUFFIX)

clean-outputs:
	rm -rf "$(OUTPUT_DIR)"

run_zigzag_data:
	@test -n "$$TUSHARE_TOKEN" || (echo "Please export TUSHARE_TOKEN first" >&2; exit 1)
	$(PYTHON) get_most_cross_section_data.py --market all --fast-reverse-today --fast-reverse-days 3

n-pattern-api:
	TZ=Asia/Shanghai N_PATTERN_DIR="$(CURDIR)/outputs/n_pattern" uvicorn backend.app:app --host "$(API_HOST)" --port "$(API_PORT)" --reload

n-pattern-web:
	cd frontend && npm run dev -- --host 0.0.0.0 --port "$(WEB_PORT)"

n-pattern-compose:
	docker compose up -d --build n-pattern-service n-pattern-api n-pattern-web

install-docker-aliyun:
	sudo ./scripts/install_docker_aliyun.sh

prod-deploy:
	./scripts/deploy_prod.sh up

prod-restart:
	./scripts/deploy_prod.sh restart

prod-status:
	./scripts/deploy_prod.sh status

prod-logs:
	./scripts/deploy_prod.sh logs

prod-down:
	./scripts/deploy_prod.sh down

prod-health:
	./scripts/deploy_prod.sh health

deploy:
	git add -A
	git diff --cached --quiet || git commit -m "$${MSG:-chore: deploy}"
	git push
	ssh root@8.130.87.199 'cd /data/NStrategy && git pull && make prod-restart'
