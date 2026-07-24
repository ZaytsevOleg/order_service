from django.core.management.base import BaseCommand
from django.conf import settings
import pandas as pd
import sqlalchemy


class Command(BaseCommand):
    help = 'Добавляет названия товаров в product_list заказов MongoDB'

    def handle(self, *args, **options):
        mongo_collection = settings.MONGO_DB['customer_order']

        self.stdout.write('Загружаю товары из MS SQL...')

        connection_string = (
            'mssql+pyodbc://BI:Olegpellich1!@10.10.2.106/1c_Warehouse'
            '?driver=ODBC+Driver+17+for+SQL+Server'
        )

        engine = sqlalchemy.create_engine(connection_string)

        product_query = """
            SELECT
                ref_key,
                Article,
                FullName
            FROM product
            WHERE DeletionMark = 0
        """

        product_df = pd.read_sql_query(product_query, engine)

        product_map = {}

        for _, row in product_df.iterrows():
            product_map[str(row['ref_key']).lower()] = {
                'product_article': row.get('Article'),
                'product_name': row.get('FullName'),
            }

        self.stdout.write(f'Товаров загружено: {len(product_map)}')

        updated_orders = 0
        updated_lines = 0
        not_found = set()

        cursor = mongo_collection.find({
            'product_list': {'$exists': True, '$ne': []}
        })

        for order in cursor:
            product_list = order.get('product_list', [])
            changed = False

            for item in product_list:
                product_key = item.get('Номенклатура_Key')

                if not product_key:
                    continue

                product_info = product_map.get(str(product_key).lower())

                if product_info:
                    if item.get('product_name') != product_info['product_name']:
                        item['product_name'] = product_info['product_name']
                        changed = True

                    if item.get('product_article') != product_info['product_article']:
                        item['product_article'] = product_info['product_article']
                        changed = True

                    updated_lines += 1
                else:
                    not_found.add(str(product_key))

            if changed:
                mongo_collection.update_one(
                    {'_id': order['_id']},
                    {'$set': {'product_list': product_list}}
                )
                updated_orders += 1

        self.stdout.write(self.style.SUCCESS(
            f'Готово. Обновлено заказов: {updated_orders}, строк товаров: {updated_lines}'
        ))

        if not_found:
            self.stdout.write(self.style.WARNING(
                f'Не найдено товаров в MS SQL: {len(not_found)}'
            ))