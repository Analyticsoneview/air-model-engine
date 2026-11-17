# Build both the customer AIR client and the dedicated administrator console.
# The two Flutter entry points are served by one local PWA image:
#   /       customer workspace
#   /admin/ administrator login and console
FROM ghcr.io/cirruslabs/flutter:stable AS base
WORKDIR /src
COPY mobile/ ./
RUN flutter create --platforms=web . && flutter pub get

FROM base AS customer-build
RUN flutter build web --release --target lib/main.dart --tree-shake-icons --no-source-maps --base-href "/" --dart-define=APP_ENV=production

FROM base AS admin-build
RUN flutter build web --release --target lib/admin_main.dart --tree-shake-icons --no-source-maps --base-href "/admin/" --dart-define=APP_ENV=production

FROM nginx:1.27-alpine
COPY deploy/nginx-air-pwa.conf /etc/nginx/conf.d/default.conf
COPY --from=customer-build /src/build/web /usr/share/nginx/html
COPY --from=admin-build /src/build/web /usr/share/nginx/html/admin
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/health || exit 1
