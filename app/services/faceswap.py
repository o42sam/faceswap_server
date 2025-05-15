from app.models.user import User
from app.crud import crud_user
from app.core.config import settings
from app.utils.custom_exceptions import AppLogicError, PaymentRequiredError
from datetime import datetime

class FaceSwapProcessor:
    async def process_swap(self, user: User, source_image_data: bytes, target_image_data: bytes) -> bytes:
        
        # 1. Check user's payment status and request limits (already handled by dependency)
        # This is an additional check or for more granular logic if needed here.
        
        is_free_tier_eligible = user.subscription_type == "none" and user.free_requests_used < settings.FREE_REQUEST_LIMIT
        is_one_time_subscriber = user.subscription_type == "one_time"
        is_monthly_subscriber_active = (
            user.subscription_type == "monthly" and
            user.subscription_end_date and
            user.subscription_end_date > datetime.utcnow() and
            user.monthly_requests_used < settings.MONTHLY_REQUEST_LIMIT
        )

        can_process = False
        is_processing_free_request = False

        if is_one_time_subscriber:
            can_process = True
        elif is_monthly_subscriber_active:
            can_process = True
        elif is_free_tier_eligible:
            can_process = True
            is_processing_free_request = True
        
        if not can_process:
            # This should ideally be caught by the FaceSwapAccessChecker dependency,
            # but as a safeguard:
            if user.subscription_type == "none" or user.subscription_type == "free_tier_used":
                 raise PaymentRequiredError(
                    detail=f"Free request limit of {settings.FREE_REQUEST_LIMIT} reached. Please subscribe for continued use.",
                    error_code="FREE_LIMIT_REACHED_PAYMENT_REQUIRED_SERVICE"
                )
            elif user.subscription_type == "monthly":
                 raise PaymentRequiredError(
                    detail="Monthly request limit reached or subscription expired. Please check your subscription.",
                    error_code="MONTHLY_LIMIT_REACHED_OR_EXPIRED_SERVICE"
                )
            else: # Should not happen if logic is correct
                 raise AppLogicError(detail="User not eligible for faceswap.", error_code="USER_NOT_ELIGIBLE_SERVICE")


        # 2. Placeholder for actual faceswap logic:
        # This is where you would integrate with the `deepfakes/faceswap` library.
        # This might involve:
        #   - Saving images to temporary files.
        #   - Calling the faceswap script as a subprocess.
        #   - Using a task queue (like Celery) for long-running jobs.
        #   - Handling errors from the faceswap process.
        
        print(f"User {user.email} is performing a faceswap.")
        if is_processing_free_request:
            print("This is a FREE request.")
        elif is_monthly_subscriber_active:
            print("This is a MONTHLY SUBSCRIBER request.")
        elif is_one_time_subscriber:
            print("This is a ONE-TIME SUBSCRIBER request (unlimited).")
            
        # Simulate processing
        # result_image_data = b"simulated_faceswapped_image_content"
        if source_image_data and target_image_data: # Basic check
            result_image_data = b"simulated_output_" + source_image_data[:10] + b"_" + target_image_data[:10]
        else:
            raise AppLogicError(detail="Source or target image data missing", error_code="IMAGE_DATA_MISSING")


        # 3. Update user's request count
        await crud_user.increment_user_request_count(user, is_free_request=is_processing_free_request)

        return result_image_data

faceswap_processor = FaceSwapProcessor()