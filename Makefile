.PHONY: check watch-check
	
TESTS := nosetests --with-coverage --cover-package=BitPy
	
check:
	$(TESTS)
	
watch-check:
	$(TESTS) --with-watch