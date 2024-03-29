import json
from time import time
import requests

import scrapy


def get_all_cats(data):
    cats = {}

    for key, value in data.items():
        title = value['title'].lower().strip()

        cats[title] = {
            'path': title,
            'url': value['url']
        }

        if value['items']:
            cats_in = get_all_cats(value["items"])
            for title_in in cats_in:
                cats[title_in] = {
                    'path': title + '$$$$' + cats_in[title_in]['path'],
                    'url': cats_in[title_in]['url']
                }

    return cats


def get_categories_from_input(input_string, categories_data):
    categories_from_input = []
    titles = set()
    input_categories = input_string.split(',')
    for cat_title in input_categories:
        cat_title = cat_title.strip().lower()
        if not categories_data.get(cat_title):
            print(f'Категория "{cat_title}" не найдена!')
        elif cat_title not in titles:
            categories_from_input.append(categories_data[cat_title])
            titles.add(cat_title)
    return categories_from_input


url = "https://api.fix-price.com/buyer/v1/category"
categories_data = requests.get(url).json()
# Рекурсивно собираю данные о категориях
categories = get_all_cats(categories_data)
cats_names_from_urls = {value['url']: key for key, value in categories.items()}


class SpiderSpider(scrapy.Spider):
    name = "spider"
    allowed_domains = ["api.fix-price.com", "fix-price.com"]

    input_categories = input("Введите категории через запятую: ").strip()
    cats_to_pars = get_categories_from_input(input_categories, categories)

    start_urls = [
        f'https://api.fix-price.com/buyer/v1/product/in/{category["url"]}?page=1&limit=24&sort=sold'
        for category in cats_to_pars
    ]

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.FormRequest(
                url,
                callback=self.parse,
                method='POST',
                formdata={},
                headers={'X-City': '55'},
            )

    def parse(self, response):
        products = json.loads(response.body)
        category_name = cats_names_from_urls[response.url.split('?page')[0].split('in/')[1]]

        for product in products:
            # Есть ли скидка
            if product['specialPrice']:
                current_price = float(product['specialPrice']['price'])
                sale = int((1 - (float(current_price) / float(product['price']))) * 100)
                sale_tag = f'Скидка {sale}%'
            else:
                current_price = float(product['price'])
                sale_tag = f'Скидка 0%'

            item = {
                'timestamp': int(time()),
                'RPC': product['id'],
                'url': f'https://fix-price.com/catalog/{product["url"]}',
                'title': product['title'],
                'marketing_tags': [],  # парсится на странице товара
                'brand': product['brand'] if not product['brand'] else product['brand']['title'],
                'section': categories[category_name]['path'].split('$$$$'),  # информация собрана заранее
                'price_data': {
                    'current': current_price,
                    'original': float(product['price']),
                    'sale_tag': sale_tag,
                },
                'stock': {
                    'in_stock': bool(int(product['inStock'])),
                    'count': int(product['inStock'])
                },
                'assets': {
                    'main_image': [image['src'] for image in product['images'] if image['id'] == product['image']][0],
                    'set_images': [image['src'] for image in product['images']],
                    'video': [],  # Я не нашел товаров с видео
                },
                'metadata': None,  # парсится на странице товара
                'variants': product['variantCount']

            }

            yield scrapy.Request(
                url=item['url'],
                callback=self.parse_product,
                meta={'product_info': item},
                headers={

                }
            )

        if products:
            next_page = int(response.url.split('page=')[1].split('&')[0]) + 1
            base_url = response.url[:response.url.find("?page=")]

            new_url = f'{base_url}?page={next_page}&limit=24&sort=sold'

            yield scrapy.FormRequest(
                new_url,
                callback=self.parse,
                method='POST',
                formdata={},
                headers={'X-City': '55'}
            )

    def parse_product(self, response):
        product_info = response.meta['product_info']

        tags_list = response.css('div.product div.wrapper.sticker div.sticker::text').getall()

        properties_list = []
        properties = response.css('div.properties p.property')
        for p in properties:
            title = p.css('span.title::text').get()
            value = p.css('span.value::text').get()
            properties_list.append([title, value])

        metadata = {
            '__description': response.css('div.product-details div.description::text').get()
        }
        metadata.update(
            {p[0]: p[1] for p in properties_list}
        )
        product_info['metadata'] = metadata
        product_info['marketing_tags'] = tags_list

        yield product_info
