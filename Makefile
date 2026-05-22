.PHONY: install seed run

install:
	python3 -m pip install -r requirements.txt

seed:
	python3 generate_data.py

run:
	python3 -m uvicorn main:app --reload
