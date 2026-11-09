
import logging
import os
import sys

from applications.services.gemini_engine import process_annual_report


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("worksphere.report_processor")


def main():
    report_id = os.getenv("REPORT_ID")

    if not report_id:
        logger.error("REPORT_ID environment variable is missing.")
        sys.exit(1)

    logger.info(
        "Starting annual report processing: %s",
        report_id,
    )

    try:
        result = process_annual_report(report_id)

        logger.info(
            "Annual report processing completed successfully: %s",
            report_id,
        )

        logger.info(
            "Processing run: %s",
            result.get("processing_run", {}).get("id"),
        )

    except Exception:
        logger.exception(
            "Annual report processing failed: %s",
            report_id,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
