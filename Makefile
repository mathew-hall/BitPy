.PHONY: check watch-check deps
	
TESTS := nosetests --with-coverage --cover-package=BitPy
	
check:
	$(TESTS)
	
watch-check:
	$(TESTS) --with-watch
	
deps:
	pip install -r requirements.txt --user