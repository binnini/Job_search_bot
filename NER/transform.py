import json
import random

# 1. 입력 파일 경로
input_path = "labelstudio_export.json"

# 2. 출력 파일 경로
train_path = "train.jsonl"
eval_path = "eval.jsonl"

# 3. 변환 + 분할 함수
def convert_and_split_labelstudio_to_gliner(input_path, train_path, eval_path, eval_ratio=0.2):
    with open(input_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    all_samples = []

    for item in raw_data:
        text = item["data"]["text"]
        entities = []

        for annotation in item["annotations"]:
            for result in annotation.get("result", []):
                value = result["value"]
                entity_text = value["text"]
                for label in value["labels"]:
                    entities.append({
                        "text": entity_text,
                        "label": label
                    })

        output_obj = {
            "text": text,
            "entities": entities
        }

        all_samples.append(output_obj)

    # 셔플 후 분할
    random.seed(42)
    random.shuffle(all_samples)

    split_idx = int(len(all_samples) * (1 - eval_ratio))
    train_data = all_samples[:split_idx]
    eval_data = all_samples[split_idx:]

    # 파일 저장
    with open(train_path, "w", encoding="utf-8") as f_train:
        for item in train_data:
            f_train.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open(eval_path, "w", encoding="utf-8") as f_eval:
        for item in eval_data:
            f_eval.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"✅ 변환 완료: Train={len(train_data)}개, Eval={len(eval_data)}개")

# 4. 실행
convert_and_split_labelstudio_to_gliner(input_path, train_path, eval_path)

