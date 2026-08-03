# Deployment archive

Build the complete portable application directly from the accepted deployment-source GeoPackage:

```sh
bash deployment/build-deployment-archive.sh \
  /path/to/kane-county.gpkg \
  /path/to/kane-offline-map.zip
```

The result has one root folder named `kane-offline-map`. It includes the browser runtime, complete prepared boundary/road/water/building data, and both portable and prepared-data integrity manifests.

The archive deliberately excludes the external `data/reviews/current/` bundle and operating-system-specific TrivialHTTP runtime files. Those are the two manual additions documented inside the archive.

`build-portable-archive.sh` remains available as the lower-level command when a separately generated complete prepared bundle already exists.
