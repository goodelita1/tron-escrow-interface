#!/usr/bin/env python3
"""
Утилиты для связывания UUID сделок с blockchain ID
"""

import json
import os
from typing import Dict, Optional

class UUIDMapping:
    """Класс для управления связыванием UUID с blockchain ID"""
    
    def __init__(self, mapping_file: str = None):
        if mapping_file is None:
            self.mapping_file = os.path.join(
                os.path.dirname(__file__), 
                'uuid_blockchain_mapping.json'
            )
        else:
            self.mapping_file = mapping_file
    
    def load_mapping(self) -> Dict[str, int]:
        """Загрузка маппинга UUID -> blockchain_id"""
        try:
            if os.path.exists(self.mapping_file):
                with open(self.mapping_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки маппинга: {e}")
        return {}
    
    def save_mapping(self, mapping: Dict[str, int]):
        """Сохранение маппинга"""
        try:
            with open(self.mapping_file, 'w', encoding='utf-8') as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения маппинга: {e}")
    
    def add_mapping(self, uuid: str, blockchain_id: int):
        """Добавление связи UUID -> blockchain_id"""
        mapping = self.load_mapping()
        mapping[uuid] = blockchain_id
        self.save_mapping(mapping)
        print(f"Добавлен маппинг: {uuid} -> {blockchain_id}")
    
    def get_blockchain_id(self, uuid: str) -> Optional[int]:
        """Получение blockchain_id по UUID"""
        mapping = self.load_mapping()
        return mapping.get(uuid)
    
    def remove_mapping(self, uuid: str):
        """Удаление маппинга"""
        mapping = self.load_mapping()
        if uuid in mapping:
            del mapping[uuid]
            self.save_mapping(mapping)
            print(f"Удален маппинг для UUID: {uuid}")
    
    def get_all_mappings(self) -> Dict[str, int]:
        """Получение всех маппингов"""
        return self.load_mapping()
    
    def cleanup_old_mappings(self, keep_count: int = 100):
        """Очистка старых маппингов (оставляем только последние keep_count)"""
        mapping = self.load_mapping()
        if len(mapping) > keep_count:
            # Оставляем только последние записи
            sorted_items = list(mapping.items())[-keep_count:]
            new_mapping = dict(sorted_items)
            self.save_mapping(new_mapping)
            removed_count = len(mapping) - keep_count
            print(f"Удалено {removed_count} старых маппингов, оставлено {keep_count}")

def main():
    """Тестирование функций маппинга"""
    mapper = UUIDMapping()
    
    # Тестовые данные
    test_uuid = "d9f4d52e-7a4e-4f66-b70c-fae4bd787720"
    test_blockchain_id = 3
    
    print("=== Тестирование UUID маппинга ===")
    
    # Добавляем маппинг
    mapper.add_mapping(test_uuid, test_blockchain_id)
    
    # Проверяем получение
    result = mapper.get_blockchain_id(test_uuid)
    print(f"Получен blockchain_id для {test_uuid}: {result}")
    
    # Показываем все маппинги
    all_mappings = mapper.get_all_mappings()
    print(f"Всего маппингов: {len(all_mappings)}")
    for uuid, blockchain_id in all_mappings.items():
        print(f"  {uuid} -> {blockchain_id}")

if __name__ == "__main__":
    main()