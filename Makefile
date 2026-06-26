PYTHON ?= python3
QLIB_DIR ?= /Users/renxg/.qlib/qlib_data/cn_data
INSTRUMENTS ?= $(QLIB_DIR)/instruments/csi300.txt
OUTPUT_DIR ?= outputs
YEARS ?= 10
WINDOW ?= 60
THRESHOLD ?= 0.001
BENCHMARK ?= sh000300
CHART_COUNT ?= 100
CHART_YEARS ?= 2
CHART_FORMAT ?= svg
CHART_OUTPUT_DIR ?= outputs/zigzag_2y_samples_svg

EXT_SUFFIX := $(shell $(PYTHON) -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')

.PHONY: help build-zigzag thiszigzag backtest zigzag-charts clean-zigzag clean-outputs

help:
	@echo "Targets:"
	@echo "  make build-zigzag  Compile thiszigzag for the active Python"
	@echo "  make backtest      Compile thiszigzag, then run the CSI300 ZigZag backtest"
	@echo "  make zigzag-charts Render recent 2-year ZigZag sample charts"
	@echo ""
	@echo "Options:"
	@echo "  PYTHON=$(PYTHON)"
	@echo "  QLIB_DIR=$(QLIB_DIR)"
	@echo "  INSTRUMENTS=$(INSTRUMENTS)"
	@echo "  OUTPUT_DIR=$(OUTPUT_DIR)"
	@echo "  YEARS=$(YEARS) WINDOW=$(WINDOW) THRESHOLD=$(THRESHOLD) BENCHMARK=$(BENCHMARK)"
	@echo "  CHART_COUNT=$(CHART_COUNT) CHART_YEARS=$(CHART_YEARS) CHART_FORMAT=$(CHART_FORMAT) CHART_OUTPUT_DIR=$(CHART_OUTPUT_DIR)"

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
		--benchmark "$(BENCHMARK)"

zigzag-charts: build-zigzag
	$(PYTHON) render_zigzag_samples.py \
		--qlib-dir "$(QLIB_DIR)" \
		--instruments "$(INSTRUMENTS)" \
		--output-dir "$(CHART_OUTPUT_DIR)" \
		--years "$(CHART_YEARS)" \
		--count "$(CHART_COUNT)" \
		--threshold "$(THRESHOLD)" \
		--format "$(CHART_FORMAT)"

clean-zigzag:
	rm -rf build
	rm -f thiszigzag/core$(EXT_SUFFIX)

clean-outputs:
	rm -rf "$(OUTPUT_DIR)"
