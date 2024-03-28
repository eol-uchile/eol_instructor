# EOL Instructor
![https://github.com/eol-uchile/eol_instructor/actions](https://github.com/eol-uchile/eol_instructor/workflows/Python%20application/badge.svg) 

# Install App

    docker-compose exec lms pip install -e /openedx/requirements/eol_instructor
    docker-compose exec lms_worker pip install -e /openedx/requirements/eol_instructor


# Configuration

Add this configuration in `LMS.yml`, by defaults is 300 seconds.

    EOL_INSTRUCTOR_TIME_CACHE: 300

## TESTS
**Prepare tests:**

    > cd .github/
    > docker-compose run lms /openedx/requirements/eol_instructor/.github/test.sh

# Notes:

- Para poder usar la pestaña de calificaciones el curso necesita tener activado las notas persistente
- Commit del tema con los cambios https://github.com/eol-uchile/eol-uchile-theme-2020/commit/d122edd781c786f6511c81a58d6c655338296004

# TO DO:

- En el tema quitar los console.log, agregar css, un loading data al apretar los botones de cargar datos, y mensajes cuando ocurra algun error
- En el tema, pestaña calificaciones hay un script de boxplot, ver si se usará finalmente el gráfico de bigotes, si se usa agregar el script como js static
- Actualizar funciones que usan notas persistentes para que usen tambien override persistant grade
- Agregar los tests
- Agregar las traducciones en el tema
- Mover los templates y scripts del tema a este repositorio