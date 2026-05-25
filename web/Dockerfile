FROM python:3.10
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIPENV_VENV_IN_PROJECT=1
RUN pip install pipenv
COPY Pipfile .
RUN pipenv install --skip-lock
ENV PATH="/.venv/bin:/usr/local/bin:/usr/bin:/bin"
WORKDIR /app
COPY . .
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]