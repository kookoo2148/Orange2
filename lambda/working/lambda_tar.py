import tarfile
import os
import boto3
import tempfile

from concurrent import futures
from io import BytesIO

# file = tarfile.open('filename.tar.gz', 'r = gz')
# file.extractall()
# file.close()

s3 = boto3.client('s3')

def lambda_handler(event, context):
    # Parse and prepare required items from event
    global bucket, path, tardata
    event = next(iter(event['Records']))
    bucket = event['s3']['bucket']['name']
    key = event['s3']['object']['key']
    path = os.path.dirname(key)

    # Create temporary file
    temp_file = tempfile.mktemp()

    # Fetch and load target file
    s3.download_file(bucket, key, temp_file)
    tardata = tarfile.open(temp_file)

    # Call action method with using ThreadPool
    with futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_list = [
            executor.submit(extract, filename)
            for filename in tardata.namelist()
        ]

    result = {'success': [], 'fail': []}
    for future in future_list:
        filename, status = future.result()
        result[status].append(filename)

    # Remove extracted archive file
    s3.delete_object(Bucket=bucket, Key=key)

    return result


def extract(filename):
    upload_status = 'success'
    try:
        s3.upload_fileobj(
            BytesIO(tardata.read(filename)),
            bucket,
            os.path.join(path, filename)
        )
    except Exception:
        upload_status = 'fail'
    finally:
        return filename, upload_status