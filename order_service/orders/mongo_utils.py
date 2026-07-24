from django.conf import settings

def get_order_items(order_id):
    db = settings.MONGO_DB
    collection = db['customer_order']

    return collection.find_one({
        'order_id': order_id
    })

def save_order_items(order_id, items):
    db = settings.MONGO_DB
    collection = db['customer_order']
    collection.update_one(
        {'ref_key': order_id},
        {'$set': {'items': items}},
        upsert=True  # Создаёт запись, если её ещё нет
    )
