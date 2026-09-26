```shell
curl http://127.0.0.1:8080/api/v1/health
curl http://127.0.0.1:8080/api/v1/alert/simple
curl -N http://127.0.0.1:8080/api/v1/stream
curl -N -H "Last-Event-ID: 1" http://127.0.0.1:8080/api/v1/stream
```
