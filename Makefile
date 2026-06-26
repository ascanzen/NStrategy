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

EXT_SUFFIX := $(shell $(PYTHON) -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')

.PHONY: help build-zigzag thiszigzag backtest zigzag-charts zigzag-signals clean-zigzag clean-outputs

help:
	@echo "Targets:"
	@echo "  make build-zigzag  Compile thiszigzag for the active Python"
	@echo "  make backtest      Compile thiszigzag, then run the CSI300 ZigZag backtest"
	@echo "  make zigzag-charts Render recent 2-year ZigZag sample charts"
	@echo "  make zigzag-signals Generate daily positive/reverse N signal files"
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
