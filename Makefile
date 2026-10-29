.PHONY: install demo run test lint docs serve

install:
	pip install -e ".[dev]"

demo:            ## whole pipeline on the bundled synthetic filings, no network
	hdq demo

run:             ## real filings from SEC EDGAR; needs SEC_USER_AGENT="Name email"
	hdq all

test:
	pytest -q

lint:
	ruff check . && ruff format --check . && sqlfluff lint controls sql

docs:
	hdq docs

serve:
	python -m http.server -d site 8000
