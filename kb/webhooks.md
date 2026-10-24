# Webhook setup

## Required events
Our server must listen for PAYMENT.CAPTURE.COMPLETED, PAYMENT.CAPTURE.REFUNDED, CUSTOMER.DISPUTE.CREATED and BILLING.SUBSCRIPTION.CANCELLED. Other events are optional.

## Testing
Use simulated events to test a new endpoint before pointing production traffic at it. Verify the signature of every webhook message before acting on it.
