FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir \
    numpy==2.2.6 pandas==2.3.3 rasterio==1.4.3 \
    geopandas==1.1.1 pyogrio==0.11.1 shapely==2.1.2 pyproj==3.7.2 \
    pillow==11.3.0
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && \
    rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 gmcompute && \
    useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin gmcompute
USER 10001:10001
WORKDIR /tmp
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
CMD ["python", "-I", "/runner.py"]
