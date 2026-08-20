from __future__ import annotations

from decimal import Decimal


class PromoEngine:

    @staticmethod
    def evaluate(
        promo,
        cart_items: list[dict],
    ) -> dict:
        """
        cart_items:
        [
            {
                "product_id": "...",
                "quantity": 2,
                "base_price": Decimal("1000.00"),
            },
            ...
        ]
        """

        cart_by_product = {
            str(item["product_id"]): item
            for item in cart_items
        }

        condition_rows = list(
            promo.condition_products.all()
        )

        condition_product_ids = {
            str(row.product_id)
            for row in condition_rows
        }

        if promo.condition_type == "fixed_set":
            return PromoEngine._evaluate_fixed_set(
                promo,
                condition_rows,
                cart_by_product,
            )

        if promo.condition_type == "total_quantity":
            return PromoEngine._evaluate_total_quantity(
                promo,
                condition_product_ids,
                cart_by_product,
            )

        if promo.condition_type == "total_amount":
            return PromoEngine._evaluate_total_amount(
                promo,
                condition_product_ids,
                cart_by_product,
            )

        return {
            "eligible": False,
            "progress": None,
            "missing": [],
        }
    @staticmethod
    def _evaluate_fixed_set(
        promo,
        condition_rows,
        cart_by_product,
    ):
        missing = []

        application_counts = []

        for row in condition_rows:

            product_id = str(
                row.product_id
            )

            required_quantity = (
                row.quantity or 0
            )

            if required_quantity <= 0:
                continue

            cart_item = (
                cart_by_product.get(
                    product_id
                )
            )

            current_quantity = (
                int(
                    cart_item["quantity"]
                )
                if cart_item
                else 0
            )

            application_counts.append(
                current_quantity
                // required_quantity
            )

            if (
                current_quantity
                < required_quantity
            ):
                missing.append(
                    {
                        "product_id":
                            product_id,

                        "name":
                            row.product.name,

                        "required":
                            required_quantity,

                        "current":
                            current_quantity,

                        "missing":
                            (
                                required_quantity
                                - current_quantity
                            ),
                    }
                )

        max_applications = (
            min(application_counts)
            if application_counts
            else 0
        )

        return {
            "eligible":
                max_applications > 0,

            "max_applications":
                max_applications,

            "progress":
                None,

            "missing":
                missing,
        }

    @staticmethod
    def _evaluate_total_quantity(
        promo,
        condition_product_ids,
        cart_by_product,
    ):
        current_quantity = 0

        for product_id in condition_product_ids:

            item = cart_by_product.get(
                product_id
            )

            if not item:
                continue

            current_quantity += int(
                item["quantity"]
            )

        required_quantity = (
            promo.threshold_quantity or 0
        )

        max_applications = (
            current_quantity
            // required_quantity
            if required_quantity > 0
            else 0
        )

        if required_quantity > 0:

            remainder = (
                current_quantity
                % required_quantity
            )

            missing_quantity = (
                0
                if remainder == 0
                else required_quantity
                - remainder
            )

        else:
            missing_quantity = 0

        return {
            "eligible":
                max_applications > 0,

            "max_applications":
                max_applications,

            "progress": {
                "type": "quantity",
                "current":
                    current_quantity,
                "required":
                    required_quantity,
                "missing":
                    missing_quantity,
            },

            "missing": [],
        }

    @staticmethod
    def _evaluate_total_amount(
        promo,
        condition_product_ids,
        cart_by_product,
    ):
        current_amount = Decimal(
            "0.00"
        )

        for product_id in condition_product_ids:

            item = cart_by_product.get(
                product_id
            )

            if not item:
                continue

            quantity = Decimal(
                str(
                    item["quantity"]
                )
            )

            base_price = Decimal(
                str(
                    item["base_price"]
                )
            )

            current_amount += (
                quantity
                * base_price
            )

        required_amount = (
            promo.threshold_amount
            or Decimal("0.00")
        )

        max_applications = (
            int(
                current_amount
                // required_amount
            )
            if required_amount > 0
            else 0
        )

        if required_amount > 0:

            remainder = (
                current_amount
                % required_amount
            )

            missing_amount = (
                Decimal("0.00")
                if remainder == 0
                else required_amount
                - remainder
            )

        else:
            missing_amount = (
                Decimal("0.00")
            )

        return {
            "eligible":
                max_applications > 0,

            "max_applications":
                max_applications,

            "progress": {
                "type": "amount",

                "current": str(
                    current_amount
                ),

                "required": str(
                    required_amount
                ),

                "missing": str(
                    missing_amount
                ),
            },

            "missing": [],
        }