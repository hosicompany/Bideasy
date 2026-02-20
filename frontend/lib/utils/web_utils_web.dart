// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;

/// Read ?token= from the current browser URL.
String? getTokenFromUrl() {
  return Uri.base.queryParameters['token'];
}

/// Read ?error= from the current browser URL.
String? getErrorFromUrl() {
  return Uri.base.queryParameters['error'];
}

/// Remove query parameters from the browser URL bar.
void cleanUrl() {
  final uri = Uri.base;
  html.window.history.replaceState(null, '', '${uri.origin}${uri.path}');
}

/// Navigate the current browser tab to the given URL.
void navigateToUrl(String url) {
  html.window.location.href = url;
}
