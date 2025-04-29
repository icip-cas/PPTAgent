# Documentation 📝

This documentation provides an overview of the project structure, setup instructions, usage guidelines, and steps for reproducing experiments.

<p align="center">
  <img src="resource/PPTAgent-workflow.jpg" alt="PPTAgent Workflow">
  <b>Figure: Workflow Illustration of PPTAgent:v0.0.1</b>
</p>

Table of Contents
=================
- [Table of Contents](#table-of-contents)
  - [Quick Start 🚀](#quick-start-)
    - [Recommendations and Requirements ⚙️](#recommendations-and-requirements-)
    - [Docker 🐳](#docker-)
    - [Running Locally 🛠](#running-locally-)
      - [Installation Guide](#installation-guide)
      - [Usage](#usage)
        - [Generate Via WebUI](#generate-via-webui)
        - [Generate Via Code](#generate-via-code)
  - [Project Structure 📂](#project-structure-)
  - [Further Step ☝️](#further-step-️)
    - [Improving generation quality 💪](#improving-generation-quality-)
    - [Contributing 🤝](#contributing-)
    - [Experimental Reproduction 🧪](#experimental-reproduction-)

## Quick Start 🚀

For a quick test, use the example in `runs/pdf(pptx)/*/source.pdf(pptx)` to save preprocessing time.

> [!NOTE]
> When using a remote server, ensure both ports `8088` and `9297` are forwarded.

### Recommendations and Requirements ⚙️

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
      <td>Minimum 8GB RAM, recommended with CUDA or MPS support for faster presentation analysis.</td>
    </tr>
    <tr>
      <td><b>Required dependencies:</b> Python 3.11+, LibreOffice, Chrome, poppler-utils (conda: poppler), NodeJS, and other system dependencies listed in our <a href="https://github.com/icip-cas/PPTAgent/blob/docker/pptagent.dockerfile">dockerfile</a>.</td>
    </tr>
  </tbody>
</table>

### Docker 🐳

```bash
# use docker proxy if you are in China
# docker pull dockerproxy.net/forceless/pptagent:latest
docker pull forceless/pptagent:latest

# mapping home directory to /root to allow caching of models
docker run -dt --gpus all --ipc=host --name pptagent \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -p 9297:9297 \
  -p 8088:8088 \
  -v $HOME:/root \
  forceless/pptagent

# set -e PULL=True to pull latest changes from the repository
# append /bin/fish to override the default command
```

It should automatically running [launch.sh](docker/launch.sh) to start the backend server.

See docker log for more running details:
```bash
docker logs -f pptagent
```

### Running Locally 🛠

#### Installation Guide

```bash
pip install git+https://github.com/icip-cas/PPTAgent.git
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
   export OPENAI_API_KEY="your_key"
   export API_BASE="http://your_service_provider/v1"
   export LANGUAGE_MODEL="Qwen2.5-72B-Instruct-GPTQ-Int4"
   export VISION_MODEL="gpt-4o-2024-08-06"
   export TEXT_MODEL="text-embedding-3-small"
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
├── pptagent_ui/                    # UI for PPTAgent
|   ├── src/                        # Frontend source code
│   ├── backend.py                  # Backend server
├── roles/                          # Role definitions in PPTAgent
├── prompts/                        # Project prompts
```

## Further Step ☝️

### Improving generation quality 💪
See [BESTPRACTICE.md](BESTPRACTICE.md) for more details.

### Contributing 🤝
So you want to contribute? Yay!

This project is actively maintained! We welcome:
- Issues: Bug reports, feature requests, and questions
- Pull Requests: Code improvements, documentation updates, and fixes
- Discussions: Share your ideas and experiences

### Experimental Reproduction 🧪
See [experiment](https://github.com/icip-cas/PPTAgent/tree/experiment) branch for reproducing experiments and evaluation results.
