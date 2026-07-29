def partition_items(items, chunk_count):
    chunk_size = max(1, len(items) // chunk_count)
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

def execute_parallel(source_path, items, workers, chunks):
    chunked = partition_items(items, chunks)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_safe_run_chunk, source_path, chunk) for chunk in chunked]
        results = [future.result() for future in futures]
    flat_values = []
    task_count = 0
    for result in results:
        flat_values.extend(result[0])
        task_count += result[1]
    return (flat_values, task_count)