import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr


env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)


conf = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME", ""),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD", ""),
    MAIL_FROM=os.getenv("MAIL_FROM", ""),
    MAIL_FROM_NAME="Mi Horario UdG",
    MAIL_PORT=int(os.getenv("MAIL_PORT", "")),
    MAIL_SERVER=os.getenv("MAIL_SERVER", ""),
    MAIL_STARTTLS=os.getenv("MAIL_STARTTLS", "").lower() == "true",
    MAIL_SSL_TLS=os.getenv("MAIL_SSL_TLS", "").lower() == "true",
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

# Instancia de FastMail
fastmail = FastMail(conf)


async def enviar_enlace_verificacion(correo_destino: EmailStr, codigo: str, base_url: str = "http://localhost:8000"):

    #Codigo es un numero de 6 digitos generado aleatoriamente
    enlace_verificacion = f"{base_url}/resenas/verificar/{codigo}"
    
    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #333;">Verificación de Reseña</h2>
            <p>Has solicitado publicar una reseña. Copia el codigo o haz clic en el enlace para publicar tu reseña:</p>
            
            <h3 style="background-color: #f4f4f4; padding: 10px; border-radius: 5px; text-align: center; font-size: 40px;">{codigo}</h3>
            <p>O haz clic en el siguiente enlace para verificar:</p>
            <p style="text-align:center"><a href="{enlace_verificacion}" style="background-color: #2563eb; color: white; padding: 10px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold; text-aling: center">Verificar Reseña</a></p>
            
            <p style="color: #999; font-size: 12px; margin-top: 30px;">
                Si no solicitaste publicar una reseña, puedes ignorar este mensaje.
            </p>
        </body>
    </html>
    """
    
    mensaje = MessageSchema(
        subject="Mi horario - Verifica Reseña",
        recipients=[correo_destino],
        body=html_body,
        subtype=MessageType.html
    )
    
    try:
        await fastmail.send_message(mensaje)
    except Exception as e:
        print(f"\n ERROR al enviar correo:")
        print(f"   Tipo: {type(e).__name__}")
        print(f"   Mensaje: {str(e)}")
        print(f"   Destinatario: {correo_destino}")
    

        raise
