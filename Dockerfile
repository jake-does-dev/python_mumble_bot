FROM python:3.10
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONFAULTHANDLER=1
ENV PYTHONUNBUFFERED=1
ENV PIPENV_VENV_IN_PROJECT=1
RUN apt-get update && apt-get install -y ffmpeg libopus0 sox && rm -rf /var/lib/apt/lists/*
RUN pip install pipenv
COPY Pipfile .
COPY Pipfile.lock .
RUN pipenv install --deploy --ignore-pipfile
ENV PATH="/.venv/bin:/usr/local/bin:/usr/bin:/bin"
WORKDIR /app
COPY . .
ENTRYPOINT ["python", "-m", "python_mumble_bot"]
CMD ["10"]