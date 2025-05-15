from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from typing import Annotated
import io

from app.models.user import User
from app.core.dependencies import get_current_active_user, FaceSwapAccessChecker
from app.services.faceswap_service import faceswap_processor
from app.utils.custom_exceptions import InvalidInputError

router = APIRouter()

@router.post("/process", dependencies=[Depends(FaceSwapAccessChecker())])
async def process_faceswap_endpoint(
    current_user: Annotated[User, Depends(get_current_active_user)], # Dependency ensures user is active
    source_image: Annotated[UploadFile, File(description="The source image containing the face to swap.")],
    target_image: Annotated[UploadFile, File(description="The target image where the face will be placed.")]
):
    if not source_image.content_type.startswith("image/") or \
       not target_image.content_type.startswith("image/"):
        raise InvalidInputError(detail="Both files must be images.", error_code="INVALID_FILE_TYPE")

    source_image_data = await source_image.read()
    target_image_data = await target_image.read()

    if not source_image_data or not target_image_data:
        raise InvalidInputError(detail="Image data could not be read or is empty.", error_code="EMPTY_IMAGE_DATA")

    # The FaceSwapAccessChecker dependency already performed checks.
    # The faceswap_processor.process_swap will handle the core logic and update counts.
    result_image_bytes = await faceswap_processor.process_swap(
        user=current_user,
        source_image_data=source_image_data,
        target_image_data=target_image_data
    )

    return StreamingResponse(io.BytesIO(result_image_bytes), media_type="image/png") # Adjust media_type if known