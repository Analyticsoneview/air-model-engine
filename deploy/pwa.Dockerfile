# Build the Flutter web client and serve it as a same-origin SPA.
FROM ghcr.io/cirruslabs/flutter:stable AS build
ARG AIR_API_BASE_URL=https://api.example.invalid
WORKDIR /src
COPY mobile/ ./
# The mobile source is shared with native builds and does not commit generated
# web platform files. Generate only the web runner in this isolated image layer.
RUN flutter create --platforms=web . \
 && flutter pub get \
 && flutter build web --release --tree-shake-icons --no-source-maps --base-href "/" \
    --dart-define=APP_ENV=production \
    --dart-define=AIR_API_BASE_URL=${AIR_API_BASE_URL}

FROM nginx:1.27-alpine
COPY deploy/nginx-air-pwa.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/build/web /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/health || exit 1
