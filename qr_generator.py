import os
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer

def generate_vendor_qr(vendor_id: str, whatsapp_url: str) -> str:
    """
    Generates a QR code for a vendor's WhatsApp link and saves it as a PNG.

    Args:
        vendor_id: The unique identifier for the vendor (e.g., "VEN-1234").
        whatsapp_url: The full WhatsApp click-to-chat URL.

    Returns:
        The relative URL path to the saved QR code image.
    """
    # Define the save path and ensure the directory exists to prevent errors.
    save_dir = "static/qr_codes"
    os.makedirs(save_dir, exist_ok=True)
    
    file_path = os.path.join(save_dir, f"{vendor_id}.png")
    
    # Generate a high-quality QR code with high error correction
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=4,
    )
    qr.add_data(whatsapp_url)
    qr.make(fit=True)

    # Create a styled image for a more professional look
    img = qr.make_image(image_factory=StyledPilImage, module_drawer=RoundedModuleDrawer())

    # Save the image file
    img.save(file_path)
        
    # Return the web-accessible URL path using forward slashes
    return f"/{save_dir.replace(os.path.sep, '/')}/{vendor_id}.png"