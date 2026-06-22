"""
python manage.py seed_data

Populates the database with realistic test data:
  - 10+ categories
  - 1000+ products
  - 20+ stores
  - 300+ inventory items per store

Design decisions:
- Uses bulk_create with batch_size=500 for efficient inserts.
- Skips existing records (ignore_conflicts=True) so safe to re-run.
- Faker provides realistic names/locations/descriptions.
"""
import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from faker import Faker

from apps.products.models import Category, Product
from apps.stores.models import Store, Inventory

fake = Faker()

CATEGORIES = [
    "Electronics", "Clothing", "Books", "Food & Beverage", "Home & Garden",
    "Sports & Outdoors", "Toys & Games", "Health & Beauty", "Automotive",
    "Office Supplies", "Musical Instruments", "Pet Supplies", "Jewelry",
    "Industrial", "Art & Crafts",
]

NUM_PRODUCTS = 1100
NUM_STORES = 25
INVENTORY_PER_STORE = 350


class Command(BaseCommand):
    help = "Seed the database with realistic dummy data"

    def handle(self, *args, **options):
        self.stdout.write("Seeding categories...")
        categories = self._seed_categories()

        self.stdout.write("Seeding products...")
        products = self._seed_products(categories)

        self.stdout.write("Seeding stores...")
        stores = self._seed_stores()

        self.stdout.write("Seeding inventory...")
        self._seed_inventory(stores, products)

        self.stdout.write(self.style.SUCCESS(
            f"Done! {len(categories)} categories, {len(products)} products, "
            f"{len(stores)} stores, ~{INVENTORY_PER_STORE} inventory items/store."
        ))

    def _seed_categories(self) -> list[Category]:
        objs = [Category(name=name) for name in CATEGORIES]
        Category.objects.bulk_create(objs, ignore_conflicts=True)
        return list(Category.objects.all())

    def _seed_products(self, categories: list[Category]) -> list[Product]:
        existing_count = Product.objects.count()
        needed = max(0, NUM_PRODUCTS - existing_count)

        if needed == 0:
            self.stdout.write("  Products already seeded.")
            return list(Product.objects.all())

        batch = []
        for _ in range(needed):
            batch.append(Product(
                title=fake.catch_phrase()[:490],
                description=fake.paragraph(nb_sentences=3) if random.random() > 0.1 else None,
                price=Decimal(str(round(random.uniform(1.99, 999.99), 2))),
                category=random.choice(categories),
            ))
            if len(batch) >= 500:
                Product.objects.bulk_create(batch)
                batch = []

        if batch:
            Product.objects.bulk_create(batch)

        return list(Product.objects.all())

    def _seed_stores(self) -> list[Store]:
        existing_count = Store.objects.count()
        needed = max(0, NUM_STORES - existing_count)

        if needed > 0:
            Store.objects.bulk_create([
                Store(
                    name=fake.company(),
                    location=fake.address().replace("\n", ", "),
                )
                for _ in range(needed)
            ], ignore_conflicts=False)

        return list(Store.objects.all())

    def _seed_inventory(self, stores: list[Store], products: list[Product]) -> None:
        for store in stores:
            existing_product_ids = set(
                Inventory.objects.filter(store=store).values_list("product_id", flat=True)
            )
            needed_products = [p for p in products if p.id not in existing_product_ids]
            sample = random.sample(needed_products, min(INVENTORY_PER_STORE, len(needed_products)))

            Inventory.objects.bulk_create([
                Inventory(
                    store=store,
                    product=product,
                    quantity=random.randint(0, 500),
                )
                for product in sample
            ], ignore_conflicts=True)

            self.stdout.write(f"  Store '{store.name}': {len(sample)} inventory items.")
