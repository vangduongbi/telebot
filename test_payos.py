from payos import PayOS
from payos.type import ItemData, PaymentData
import time

PAYOS_CLIENT_ID = "fade3e3e-9f8b-4c4b-93ea-e195c78c7d2f"
PAYOS_API_KEY = "9940c4a4-6375-416c-89ac-81f791d4d631"
PAYOS_CHECKSUM_KEY = "d8c8841f3210b28f3c7e2047fc5460a65c3343b5f81053fbb5af90816688e4fb"

try:
    payos_client = PayOS(client_id=PAYOS_CLIENT_ID, api_key=PAYOS_API_KEY, checksum_key=PAYOS_CHECKSUM_KEY)
    print("PayOS methods:", dir(payos_client))
    if hasattr(payos_client, "createPaymentLink"):
        # Older SDK versions maybe?
        payment_data = PaymentData(orderCode=int(time.time()), amount=2000, description="Test", cancelUrl="http://127.0.0.1", returnUrl="http://127.0.0.1")
        link = payos_client.createPaymentLink(paymentData=payment_data)
        print("Link:", link)
except Exception as e:
    print("Error init 1:", e)

try:
    from payos.types import CreatePaymentLinkRequest
    payos_client = PayOS(client_id=PAYOS_CLIENT_ID, api_key=PAYOS_API_KEY, checksum_key=PAYOS_CHECKSUM_KEY)
    
    payment_request = CreatePaymentLinkRequest(
        order_code=int(time.time()),
        amount=2000,
        description="Thanh toan don hang",
        cancel_url="http://127.0.0.1/cancel",
        return_url="http://127.0.0.1/success"
    )
    payment_link = payos_client.payment_requests.create(payment_request)
    print("checkout_url:", getattr(payment_link, 'checkout_url', None))
    print("qr_code:", getattr(payment_link, 'qr_code', None))
    print("Link object dump:", vars(payment_link))
except Exception as e:
    print("Error init 2:", e)
    import traceback
    traceback.print_exc()
