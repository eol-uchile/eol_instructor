.DEFAULT_GOAL := help
.PHONY: requirements

# include *.mk

help: ## Display this help message
	@echo "Please use \`make <target>' where <target> is one of"
	@perl -nle'print $& if m{^[\.a-zA-Z_-]+:.*?## .*$$}' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m  %-25s\033[0m %s\n", $$1, $$2}'


lang_targets = es_419
create_translations_catalogs: ## Create the initial configuration of .mo files for translation
	pybabel extract -F eol_instructor/locale/babel.cfg -o  eol_instructor/locale/django.pot --msgid-bugs-address=eol-ayuda@uchile.cl --copyright-holder=EOL *
	for lang in $(lang_targets) ; do \
        pybabel init -i eol_instructor/locale/django.pot -D django -d eol_instructor/locale/ -l $$lang ; \
        pybabel init -i eol_instructor/locale/django.pot -D djangojs -d eol_instructor/locale/ -l $$lang ; \
    done


update_translations: ## update strings to be translated
	pybabel extract -F eol_instructor/locale/babel.cfg -o eol_instructor/locale/django.pot *
	pybabel update -N -D django -i eol_instructor/locale/django.pot -d eol_instructor/locale/
	pybabel update -N -D djangojs -i eol_instructor/locale/django.pot -d eol_instructor/locale/
	rm eol_instructor/locale/django.pot


compile_translations: ## compile .mo files into .po files
	pybabel compile -f -D django -d eol_instructor/locale/; \
	pybabel compile -f -D djangojs -d eol_instructor/locale/