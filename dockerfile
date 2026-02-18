FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir requests pandas pyyaml

# Copy script files
COPY . .

# Set the default command (allows passing arguments like --dry-run)
ENTRYPOINT ["python", "link_livephoto_videos.py"]