FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2 and pandas
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir requests psycopg2-binary pandas pyyaml

# Copy script files
COPY . .

# Set the default command (allows passing arguments like --dry-run)
ENTRYPOINT ["python", "link_livephoto_videos.py"]