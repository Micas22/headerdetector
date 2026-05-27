FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Copy requirements
COPY requirements.txt /app/

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers and dependencies
RUN playwright install chromium --with-deps

# Copy project
COPY . /app/

# Expose port
EXPOSE 5000

# Run the application
CMD ["gunicorn", "--workers=2", "--threads=8", "--bind=0.0.0.0:5000", "app:app"]
