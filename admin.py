import uuid
from fastapi import APIRouter, Depends, Body, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.utils.qr_generator import generate_vendor_qr

router = APIRouter()

@router.post("/onboard", status_code=201)
async def onboard_new_vendor(
    vendor_name: str = Body(..., embed=True, description="Name of the new vendor"),
    phone_number: str = Body(..., embed=True, description="Vendor's WhatsApp phone number (e.g., 2348012345678)"),
    db: Session = Depends(get_db)
):
    """
    Onboards a new vendor, creates a QR code for their WhatsApp,
    and returns the vendor details.
    """
    # In a real application, you would save the new vendor to the database here.
    # For this example, we'll just generate a unique ID.
    vendor_id = f"VEN-{str(uuid.uuid4())[:8].upper()}"
    
    # Construct the WhatsApp click-to-chat URL.
    whatsapp_url = f"https://wa.me/{phone_number}"
    
    # Generate and save the QR code image using the utility function.
    qr_file_path = generate_vendor_qr(vendor_id=vendor_id, whatsapp_url=whatsapp_url)
    
    # Return the new vendor's details, including the path to the QR code image.
    return {
        "detail": "Vendor onboarded successfully.",
        "vendor_id": vendor_id,
        "qr_image_url": qr_file_path
    }