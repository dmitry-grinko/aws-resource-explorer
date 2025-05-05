# AWS Resource Relationship Explorer

This script provides a simple command-line interface to explore predefined relationships between mock AWS resources.

## Setup and Dependencies

This project uses Python 3 and requires external packages listed in `requirements.txt`. It is highly recommended to use a virtual environment to manage dependencies.

**1. Create a Virtual Environment:**

   *   **macOS / Linux:**
       ```bash
       python3 -m venv venv
       ```
   *   **Windows (cmd/powershell):**
       ```bash
       python -m venv venv
       ```
   (Replace `venv` with your preferred environment name if desired).

**2. Activate the Virtual Environment:**

   *   **macOS / Linux:**
       ```bash
       source venv/bin/activate
       ```
   *   **Windows (cmd):**
       ```bash
       venv\Scripts\activate.bat
       ```
   *   **Windows (powershell):**
       ```bash
       .\venv\Scripts\Activate.ps1
       ```
       (If you encounter execution policy issues on PowerShell, you might need to run `Set-ExecutionPolicy RemoteSigned -Scope Process` first).

   Your terminal prompt should change to indicate the active environment (e.g., `(venv) Your-Computer:...$`).

**3. Install Dependencies:**

   With the virtual environment activated, run:
   ```bash
   pip install -r requirements.txt
   ```

**4. Deactivate (When Done):**

   Simply run:
   ```bash
   deactivate
   ```

## Functionality

*   **Data Driven:** Resource information (name, type, account) and their relationships (invokes, invoked_by) are stored in `resources.json`. **Note:** This file is generated/updated by `cloudformation_parser.py`.
*   **Interactive Exploration:** Users can enter the name of a known AWS resource to start.
*   **Relationship Display:** The script displays the entered resource's type and account, then shows two tables:
    *   `Invokes`: Resources called or used by the current resource.
    *   `Invoked by`: Resources that call or use the current resource.
*   **Table Contents:** Each table lists the related resource's name, type, and AWS account name.
*   **Recursive Navigation:** Users can select a resource number from the tables to navigate to that resource and explore its relationships.
*   **Case-Insensitive Input:** The initial resource name entered by the user is treated case-insensitively.
*   **Quit Option:** Users can type 'q' at any prompt to exit the program.
*   **CloudFormation Parser:** A parser script `cloudformation_parser.py` can process CloudFormation templates (YAML) and update the `resources.json` data file. It attempts to infer relationships based on common patterns (`!Ref`, `!GetAtt`, `!Sub`, EventSourceMappings, etc.). The parser reads the existing `resources.json`, merges the new data from the provided template(s), and writes the combined result back.
*   **Data Validation:** A test script `test.py` can be run (`python test.py`) to check if all resources mentioned in relationships within `resources.json` have their own top-level definitions.

## Data Structure (`resources.json`)

The data file stores a JSON object mapping resource logical IDs to their details:

```json
{
    "ResourceNameA": {
        "type": "ResourceType",
        "account_name": "AccountName",
        "invokes": [
            {
                "name": "ResourceNameB",
                "type": "ResourceTypeB",
                "account_name": "AccountB"
            }
        ],
        "invoked_by": [
            {
                "name": "ResourceNameC",
                "type": "ResourceTypeC",
                "account_name": "AccountC"
            }
        ]
    }
}
```

## How to Run the Explorer (`main.py`)

1.  Ensure you have Python 3 installed.
2.  Follow the **Setup and Dependencies** steps (create/activate virtual environment, install `PyYAML` via `pip install -r requirements.txt`).
3.  **Generate `resources.json`:** Run the parser against one or more CloudFormation templates (see below).
4.  Run the main script (ensure `venv` is active):
    ```bash
    python main.py
    ```
5.  Follow the prompts.

## How to Run the Parser (`cloudformation_parser.py`)

This script updates the `resources.json` file.

```bash
# Activate virtual environment first
# source venv/bin/activate

# Run against one template (will create or update resources.json)
python cloudformation_parser.py <path_to_template.yml> <aws_account_name>

# Run against multiple templates (merges data into resources.json)
python cloudformation_parser.py template1.yml acc1 template2.yml acc2 ...
```

Example using the included `parse.sh` (run this first to generate initial data):
```bash
./parse.sh 
```
*(Note: You might need to make it executable: `chmod +x parse.sh`)*

## Running the Validation Test (`test.py`)

With the virtual environment activated and after `resources.json` has been generated:
```bash
python test.py
``` 