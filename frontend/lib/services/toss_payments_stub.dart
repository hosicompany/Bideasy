// Stub implementation for non-web platforms.

Future<void> requestTossPayment({
  required String clientKey,
  required String orderId,
  required int amount,
  required String orderName,
  required String customerName,
  required String successUrl,
  required String failUrl,
}) async {
  throw UnsupportedError('Toss Payments is only supported on web');
}
