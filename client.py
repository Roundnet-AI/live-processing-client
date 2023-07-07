import boto3
from pathlib import Path
import json
import os
import configparser
import time
import threading
import signal
import sys
import traceback
import tqdm
from playsound import playsound

class FileManagerClient:
    def __init__(self, upload_bucket: str, download_bucket: str, aws_access_key_id: str, aws_secret_access_key: str, input: str = "./input", output: str = "./output", **kwargs):
        """Initialize FileManagerClient for managing input and output files.

        Args:
            upload_bucket (str): S3 bucket to upload files to.
            download_bucket (str): S3 bucket to download files from.
            aws_access_key_id (str): AWS access key ID.
            aws_secret_access_key (str): AWS secret access key.
            input (str, optional): Input file folder. Defaults to "./input".
            output (str, optional): Output file folder. Defaults to "./output".

        Kwargs:
            upload_history (str, optional): Upload history file. Defaults to 
                "upload_history.json".
            download_history (str, optional): Download history file. Defaults to
                "download_history.json".
            sleep_interval (int, optional): Sleep interval in seconds. Defaults
                to 30.
        """
        self.input = Path(input)
        self.input_archive = Path(input + "_archive")
        self.output = Path(output)
        self.upload_bucket = upload_bucket
        self.download_bucket = download_bucket
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )
        if not self.input.exists():
            self.input.mkdir()
        if not self.output.exists():
            self.output.mkdir()
        if not self.input_archive.exists():
            self.input_archive.mkdir()
        self.upload_fp = kwargs.get("upload_history", "upload_history.json")
        self.download_fp = kwargs.get("download_history", "download_history.json")
        if not (Path(self.upload_fp)).exists():
            print("Upload history file not found. Creating...")
            with open(self.upload_fp, "w") as f:
                json.dump([], f)
        if not (Path(self.download_fp)).exists():
            print("Download history file not found. Creating...")
            with open(self.download_fp, "w") as f:
                json.dump([], f)
        self.upload_history = json.load(open(self.upload_fp))
        self.download_history = json.load(open(self.download_fp))
        self.sleep_interval = kwargs.get("sleep_interval", 10)
        self.running = True

    def _check_input_files(self) -> "list[Path]":
        """Check for new input files.

        Returns:
            list[Path]: List of all files in input folder.
        """
        files = list(self.input.glob("*"))
        return files

    def _upload_files(self, files: "list[Path]"):
        """Upload files to S3.

        Args:
            files (list[Path]): List of files to upload.
        """
        for file in files:
            self._upload_file(file)

    def _upload_file(self, file: Path):
        """Upload file to S3.

        Args:
            file (Path): File to upload.
        """
        if " " in file.name:
            print(f"Renaming {file} without spaces.")
            os.rename(file, file.with_name(file.name.replace(" ", "_")))
            file = file.with_name(file.name.replace(" ", "_"))
        print(f"Uploading {file} to S3...")
        file_size = os.stat(file).st_size
        with tqdm.tqdm(total=file_size, unit="B", unit_scale=True, desc=file.name) as pbar:
            self.s3.upload_file(
                Filename=file,
                Bucket=self.upload_bucket,
                Key=file.name,
                Callback=lambda bytes_transferred: pbar.update(bytes_transferred),
            )
        self.upload_history.append(file.name)
        with open(self.upload_fp, "w") as f:
            json.dump(self.upload_history, f)
        os.rename(file, self.input_archive / file.name)
    
    def _manage_input(self):
        while self.running:
            files = self._check_input_files()
            if files:
                self._upload_files(files)
            time.sleep(self.sleep_interval)

    def _manage_output(self):
        while self.running:
            self._check_for_downloads()
            time.sleep(self.sleep_interval)

    def _check_for_downloads(self):
        files = self._list_s3_files()
        for file in files:
            if file not in self.download_history:
                self._download_file(file)

    def _list_s3_files(self) -> "list[str]":
        files = []
        objs = self.s3.list_objects(Bucket=self.download_bucket)
        if "Contents" in objs:
            for obj in objs["Contents"]:
                files.append(obj["Key"])
        return files

    def _download_file(self, file: str):
        print(f"Downloading {file} from S3...")
        self.s3.download_file(self.download_bucket, file, self.output / file)
        playsound("notify.mp3")
        self.download_history.append(file)
        with open(self.download_fp, "w") as f:
            json.dump(self.download_history, f)

if __name__ == "__main__":
    try:
        assert os.path.exists("Config.ini"), "Config.ini file not found. Please restore or create it."
        assert os.path.exists("Login.ini"), "Login.ini file not found. Please restore or create it."
        print("""    ____    ____    __  __    _   __    ____     _   __    ______  ______           ___     ____
   / __ \  / __ \  / / / /   / | / /   / __ \   / | / /   / ____/ /_  __/          /   |   /  _/
  / /_/ / / / / / / / / /   /  |/ /   / / / /  /  |/ /   / __/     / /            / /| |   / /  
 / _, _/ / /_/ / / /_/ /   / /|  /   / /_/ /  / /|  /   / /___    / /            / ___ | _/ /   
/_/ |_|  \____/  \____/   /_/ |_/   /_____/  /_/ |_/   /_____/   /_/            /_/  |_|/___/   
                                                                                                """)
        print("Starting client...")
        print("To terminate, close the terminal window at any time.")
        config = configparser.ConfigParser()
        config.read(["Config.ini", "Login.ini"])
        client = FileManagerClient(
            upload_bucket=config["S3"]["input_bucket"],
            download_bucket=config["S3"]["output_bucket"],
            aws_access_key_id=config["AWS"]["aws_access_key_id"],
            aws_secret_access_key=config["AWS"]["aws_secret_access_key"],
        )

        # Create two threads for manage_input and manage_output
        input_thread = threading.Thread(target=client._manage_input)
        output_thread = threading.Thread(target=client._manage_output)

        # Start both threads
        input_thread.start()
        output_thread.start()

        # Function to handle termination signal
        def handle_termination_signal(signal, frame):
            print("Gracefully terminating (~30s)...")
            client.running = False
            input_thread.join()
            output_thread.join()
            sys.exit(0)

        # Register the termination signal handler
        signal.signal(signal.SIGINT, handle_termination_signal)
        signal.signal(signal.SIGTERM, handle_termination_signal)

        # Keep the main thread alive
        while True:
            time.sleep(1)
    except Exception as e:
        trace = traceback.format_exc()
        print(trace)
        input("Application failed. Read above information to determine root cause.")