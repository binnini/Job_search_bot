import csv

def save_to_csv(output_csv, data_batch, header):
    with open(output_csv, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(header)
        writer.writerows(data_batch)
