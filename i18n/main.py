import hashlib
import json
import os
import shutil
import stat

from git import Repo
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

absolute_path = os.path.abspath(__file__)
i18n_directory = os.path.dirname(absolute_path)
repo_directory = os.path.dirname(i18n_directory)

readme_section = """
## Uwaga odnośnie tłumaczenia

Wszystkie pliki pochodzą z repozytorium [bronze-qiskit](https://gitlab.com/qworld/bronze-qiskit.git). Wszystkie problemy z działaniem kodu należy kierować na tamto repozytorium.
W tym repozytorium należy zgłaszać jedynie uwagi odnośnie błędnych tłumaczeń.\n\n\n\n
"""

llm = ChatOpenAI(model="gpt-3.5-turbo")
system_template = """
You are a thorough and meticulous translator.
Every time `notebooks` is mentioned, it is about Jupyter notebooks.
Your task is to translate a file in {file_format} format preserving the source formatting from English to Polish.
"""
human_template = "{text}"
chat_prompt = ChatPromptTemplate.from_messages([
    ("system", system_template),
    ("human", human_template),
])


def make_dir_writable(function, path, exception):
    """The path on Windows cannot be gracefully removed due to being read-only,
    so we make the directory writable on a failure and retry the original function.
    """
    os.chmod(path, stat.S_IWRITE)
    function(path)


def clone_repository():
    repo_url = "https://gitlab.com/qworld/bronze-qiskit.git"
    fork_directory = os.path.join(i18n_directory, "fork")
    if not os.path.exists(fork_directory):
        Repo.clone_from(repo_url, fork_directory)
        shutil.rmtree(os.path.join(fork_directory, ".git"), onerror=make_dir_writable)
    exclude_list = [".git", ".venv", "i18n", ".idea"]
    for item in os.listdir(repo_directory):
        item_path = os.path.join(repo_directory, item)
        if item not in exclude_list:
            if os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
    shutil.copytree(fork_directory, repo_directory, dirs_exist_ok=True)
    with open(os.path.join(repo_directory, ".gitignore"), "a", encoding="utf-8") as f:
        f.write(".idea\n")
        f.write("i18n/fork\n")
        f.write(".venv\n")


def list_files_in_directory(directory):
    excludes = [
        os.path.join("i18n", "fork"),
        os.path.join("i18n", "cache"),
        "LICENSE.md",
        ".venv",
        ".idea",
        ".ipynb_checkpoints",
    ]

    includes_ext = [
        ".md", ".ipynb"
    ]

    file_list = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            abs_path = os.path.join(root, file)
            should_add = False
            for i in includes_ext:
                if abs_path.lower().endswith(i.lower()):
                    should_add = True
            if should_add:
                for e in excludes:
                    if e.lower() in abs_path.lower():
                        should_add = False
            if should_add:
                file_list.append(abs_path)
    return file_list


def translate(text, text_type):
    print("Translate " + text[:64].replace("\n", " ") + "...")
    prompt = chat_prompt.format_messages(file_format=text_type, text=text)
    output = llm.invoke(prompt)
    return output.content


def cache_file(file):
    cache_directory = os.path.join(i18n_directory, "cache")
    relative_file_path = file.replace(repo_directory + os.sep, '')
    cache_path = os.path.join(cache_directory, relative_file_path + ".json")
    parent_cache_path = os.path.dirname(cache_path)
    if not os.path.exists(parent_cache_path):
        os.makedirs(parent_cache_path)
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data, cache_path
    else:
        return {}, cache_path


def calculate_md5(text):
    md5_hash = hashlib.md5()
    md5_hash.update(text.encode('utf-8'))
    return md5_hash.hexdigest()


def get_translate(file, origin):
    data, _ = cache_file(file)
    file_hash = calculate_md5(origin)
    if file_hash in data:
        return data[file_hash]["translate"]
    else:
        return None


def store_translate(file, origin, new):
    data, cache_path = cache_file(file)
    file_hash = calculate_md5(origin)
    data[file_hash] = dict(origin=origin, translate=new)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def process_markdown(file, text=None):
    def count_newlines_at_end(s):
        count = 0
        for i in range(len(s) - 1, -1, -1):  # Start from the end of the string
            if s[i] == '\n':
                count += 1
            else:
                break  # Exit the loop if a character other than newline is encountered
        return count

    sections = []
    section = ""
    if text is None:
        with open(file, "r", encoding="UTF-8") as f:
            for line in f.readlines():
                if line.startswith("#"):
                    sections.append(section)
                    section = ""
                section += line + "\n"
        sections.append(section)
    else:
        for line in text.splitlines():
            if line.startswith("#"):
                sections.append(section)
                section = ""
            section += line + "\n"
        sections.append(section)
    new_sections = []
    for section in sections:
        new = get_translate(file, section)
        if new is None:
            count_end_new_lines = count_newlines_at_end(section)
            new = translate(section, text_type="Markdown")
            new += "\n" * count_end_new_lines
            store_translate(file, section, new)
        new_sections.append(new)
    if text:
        return "\n".join(new_sections)
    else:
        if "README.md" in file:
            new_sections.insert(1, readme_section)
        with open(file, "w", encoding="UTF-8") as f:
            f.writelines(new_sections)


def process_notebook(file):
    with open(file, "r", encoding="UTF-8") as f:
        data = json.load(f)
    for cell in data["cells"]:
        if cell["cell_type"] == "markdown":
            text = "".join(cell["source"])
            trans = process_markdown(file, text)
            new_source = []
            for line in trans.splitlines():
                new_source.append(line + "\n")
            cell["source"] = new_source
    with open(file, "w", encoding="UTF-8") as f:
        json.dump(data, f)
    pass


if __name__ == "__main__":

    clone_repository()
    files = list_files_in_directory(repo_directory)

    for file in files:
        if file.endswith(".md"):
            process_markdown(file)
        elif file.endswith(".ipynb"):
            process_notebook(file)
