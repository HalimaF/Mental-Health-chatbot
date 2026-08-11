web: flask --app wsgi db upgrade && gunicorn wsgi:app --workers ${WEB_CONCURRENCY:-2} --threads 4 --timeout 60 --access-logfile - --error-logfile -
