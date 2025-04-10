# Documentation 📝

This documentation provides an overview of the project structure, setup instructions, usage guidelines, and steps for reproducing experiments.

<p align="center">
  <img src="resource/PPTAgent-workflow.jpg" alt="PPTAgent Workflow">
  <b>Figure: Workflow Illustration of PPTAgent:v0.0.1</b>
</p>

Table of Contents
=================
- [Documentation 📝](#documentation-)
- [Table of Contents](#table-of-contents)
  - [Quick Start 🚀](#quick-start-)
    - [Recommendations and Requirements](#recommendations-and-requirements)
    - [Docker 🐳](#docker-)
    - [Running Locally 🛠](#running-locally-)
      - [Installation Guide](#installation-guide)
      - [Usage](#usage)
        - [Generate Via WebUI](#generate-via-webui)
        - [Generate Via Code](#generate-via-code)
  - [Project Structure 📂](#project-structure-)

## Quick Start 🚀
For a quick test, use the example in `resource/test/test_(pdf|template)` to save preprocessing time.

### Recommendations and Requirements

<table>
  <thead>
    <tr>
      <th>Category</th>
      <th>Details</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td rowspan="2"><b>LLM Recommendations</b></td>
      <td>Language Model: 70B+ non-reasoning model (Qwen2.5-72B-Instruct), for generation tasks.</td>
    </tr>
    <tr>
      <td>Vision Model: 7B+ parameters (Qwen2-VL-7B-Instruct), for captioning tasks.</td>
    </tr>
    <tr>
      <td rowspan="3"><b>System Requirements</b></td>
      <td>Tested on Linux and macOS, <b>Windows is not supported</b>.</td>
    </tr>
    <tr>
      <td>Minimum 8GB RAM, recommended with CUDA or MPS support for better performance.</td>
    </tr>
    <tr>
      <td><b>Required dependencies:</b> LibreOffice, Chrome, poppler-utils (conda: poppler), and NodeJS.</td>
    </tr>
  </tbody>
</table>

### Docker 🐳

> [!CAUTION]
> As we cannot update the Docker image promptly, we recommend building your own Docker image instead.

> [!NOTE]
> When using a remote server, ensure both ports `8088` and `9297` are forwarded.

```bash
docker pull forceless/pptagent
docker run -dt --gpus all --ipc=host --name pptagent \
  -e OPENAI_API_KEY='your_key' \
  -p 9297:9297 \
  -p 8088:8088 \
  -v $HOME:/root \
  forceless/pptagent
```

```bash
docker exec -it pptagent bash
# serve backend
cd pptagent_ui
python3 backend.py &
# serve frontend
npm install
npm run serve
```

### Running Locally 🛠

#### Installation Guide

```bash
pip install git+https://github.com/icip-cas/PPTAgent.git
pip install git+https://github.com/Force1ess/python-pptx
```

#### Usage

##### Generate Via WebUI

1. **Serve Backend**

   Initialize your models in `pptagent_ui/backend.py`:
   ```python
   language_model = AsyncLLM(
       model="Qwen2.5-72B-Instruct",
       api_base="http://localhost:7812/v1"
   )
   vision_model = AsyncLLM(model="gpt-4o-2024-08-06")
   text_embedder = AsyncLLM(model="text-embedding-3-small")
   ```
   Or use the environment variables:

   ```bash
   export LANGUAGE_MODEL="Qwen2.5-72B-Instruct-GPTQ-Int4"
   export LANGUAGE_MODEL_API_BASE="http://localhost:7812/v1"
   export VISION_MODEL="gpt-4o-2024-08-06"
   export VISION_MODEL_API_BASE="http://localhost:7812/v1"
   export TEXT_MODEL="text-embedding-3-small"
   export TEXT_MODEL_API_BASE="http://localhost:7812/v1"
   ```

2. **Launch Frontend**

   > Note: The backend API endpoint is configured at `pptagent_ui/vue.config.js`

   ```bash
   cd pptagent_ui
   npm install
   npm run serve
   ```

##### Generate Via Code

For detailed information on programmatic generation, please refer to the `pptagent_ui/backend.py:ppt_gen` and `test/test_pptgen.py`.

## Project Structure 📂

```
PPTAgent/
├── presentation/                   # Parse PowerPoint files
├── document/                       # Organize markdown document
├── pptagent/
│   ├── apis.py                     # API and CodeExecutor
│   ├── agent.py                    # Defines the `Agent` and `AsyncAgent`
│   ├── llms.py                     # Defines the `LLM` and `AsyncLLM`
│   ├── induct.py                   # Presentation analysis (Stage Ⅰ)
│   ├── pptgen.py                   # Presentation generation (Stage Ⅱ)
│   ├── layout.py                   # Definition of the layout in pptxs
├── pptagent_ui/                    # UI for PPTAgent
|   ├── src/                        # Frontend source code
│   ├── backend.py                  # Backend server
├── roles/                          # Role definitions in PPTAgent
├── prompts/                        # Project prompts
```
