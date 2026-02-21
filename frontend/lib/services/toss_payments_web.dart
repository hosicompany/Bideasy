import 'dart:js_interop';

@JS('requestTossPaymentJS')
external void _requestTossPaymentJS(
  JSString clientKey,
  JSString orderId,
  JSNumber amount,
  JSString orderName,
  JSString customerName,
  JSString successUrl,
  JSString failUrl,
);

Future<void> requestTossPayment({
  required String clientKey,
  required String orderId,
  required int amount,
  required String orderName,
  required String customerName,
  required String successUrl,
  required String failUrl,
}) async {
  _requestTossPaymentJS(
    clientKey.toJS,
    orderId.toJS,
    amount.toJS,
    orderName.toJS,
    customerName.toJS,
    successUrl.toJS,
    failUrl.toJS,
  );
}
