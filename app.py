import pandas as pd
import streamlit as st

from algebra_engine import (
    AlgebraError,
    validate_elements,
    validate_operation,
    generate_operation_table,
    check_properties,
    detect_structure,
    check_distributivity,
    detect_pair_structure,
    verify_theorem,
)
from database import (
    initialize_database,
    save_theorem,
    list_theorems,
    delete_theorem,
    save_algebra,
    list_algebras,
    delete_algebra,
    register_user,
    authenticate_user,
    storage_backend,
)

st.set_page_config(
    page_title="Advanced Algebra Engine",
    page_icon="📐",
    layout="wide"
)
try:
    initialize_database()
except Exception as exc:
    st.error("The database connection is not ready. Check your Streamlit Secrets and Supabase schema.")
    st.exception(exc)
    st.stop()

# ----------------------------- Authentication -----------------------------
st.title("📐 Advanced Algebraic Theorem Verification Engine")
st.caption("Finite algebra structures • theorem verification • proof traces • personal libraries")

if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None

if not st.session_state.authenticated_user:
    login_tab, register_tab = st.tabs(["Log in", "Create account"])
    with login_tab:
        st.subheader("Welcome back")
        with st.form("login_form"):
            login_username = st.text_input("Username")
            login_password = st.text_input("Password", type="password")
            login_submit = st.form_submit_button("Log in", type="primary")
        if login_submit:
            if authenticate_user(login_username, login_password):
                st.session_state.authenticated_user = login_username.strip().lower()
                st.rerun()
            else:
                st.error("Incorrect username or password.")
    with register_tab:
        st.subheader("Create your personal account")
        st.caption("Your saved algorithms and algebra configurations are private to your account. Passwords must be at least 10 characters.")
        with st.form("register_form"):
            new_username = st.text_input("Choose a username")
            new_password = st.text_input("Choose a password", type="password")
            confirm_password = st.text_input("Confirm password", type="password")
            register_submit = st.form_submit_button("Create account", type="primary")
        if register_submit:
            if new_password != confirm_password:
                st.error("The passwords do not match.")
            else:
                ok, message = register_user(new_username, new_password)
                (st.success if ok else st.error)(message)
    st.info("Create an account or log in to open your private algebra workspace.")
    st.stop()

current_user = st.session_state.authenticated_user
with st.sidebar:
    st.markdown(f"**Signed in as:** `{current_user}`")
    st.caption(f"Storage: {storage_backend()}")
    if storage_backend().startswith("SQLite"):
        st.warning("Local SQLite mode: cloud data may not persist. Configure Supabase before publishing.")
    if st.button("Log out", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

if "elements" not in st.session_state:
    st.session_state.elements = ["0", "1"]
if "theta_values" not in st.session_state:
    st.session_state.theta_values = {}
if "phi_values" not in st.session_state:
    st.session_state.phi_values = {}

tabs = st.tabs([
    "Workspace",
    "Operation Generator",
    "Structure Detection",
    "Theorem & Proof Library",
    "Saved Algebras"
])

def table_to_df(elements, table):
    return pd.DataFrame(
        [[table.get((a, b), "") for b in elements] for a in elements],
        index=elements,
        columns=elements
    )

def df_to_table(df, elements):
    return {
        (str(a), str(b)): str(df.loc[a, b]).strip()
        for a in elements for b in elements
    }

def show_property(label, item):
    if item["holds"]:
        st.success(f"✓ {label}")
    else:
        st.error(f"✗ {label}")
        if item.get("counterexample"):
            st.json(item["counterexample"])

with tabs[0]:
    st.subheader("Define your algebra")
    st.caption("Edits are kept in the workspace. Load or change the set only when you press the relevant button.")

    # Apply generated tables before the editors are instantiated on this run.
    if "pending_generated" in st.session_state:
        pending = st.session_state.pop("pending_generated")
        st.session_state.elements = pending["elements"]
        st.session_state.elements_input = ",".join(pending["elements"])
        if pending["target"] == "θ":
            st.session_state.theta_values = pending["table"]
        else:
            st.session_state.phi_values = pending["table"]
        st.session_state.pop("theta_editor", None)
        st.session_state.pop("phi_editor", None)
        st.session_state.pop("workspace_validation", None)

    # Loading is an explicit action. Previously, the selected saved algebra was
    # reloaded on every rerun, which overwrote unsaved cell edits.
    saved_algebras = list_algebras(current_user)
    saved_options = {f'{a["name"]} (#{a["id"]})': a for a in saved_algebras}
    load_col, load_btn_col = st.columns([4, 1])
    with load_col:
        chosen_saved = st.selectbox(
            "Load saved algebra",
            ["— Select a saved algebra —"] + list(saved_options),
            key="saved_algebra_choice",
        )
    with load_btn_col:
        st.write("")
        st.write("")
        load_clicked = st.button("Load", disabled=chosen_saved == "— Select a saved algebra —")
    if load_clicked:
        match = saved_options[chosen_saved]
        st.session_state.elements = match["elements"]
        st.session_state.theta_values = match["theta"]
        st.session_state.phi_values = match["phi"]
        st.session_state.elements_input = ",".join(match["elements"])
        # A new algebra may have a different shape; reset only the editor widget state.
        st.session_state.pop("theta_editor", None)
        st.session_state.pop("phi_editor", None)
        st.session_state.pop("workspace_validation", None)
        st.success(f'Loaded {match["name"]}.')
        st.rerun()

    st.markdown("**Set elements**")
    element_col, apply_col = st.columns([4, 1])
    with element_col:
        elements_draft = st.text_input(
            "Elements (comma separated)",
            value=",".join(st.session_state.elements),
            key="elements_input",
            help="Example: 0,1,2. Press Apply set to resize the operation tables.",
        )
    with apply_col:
        st.write("")
        st.write("")
        apply_elements = st.button("Apply set", type="secondary")

    if apply_elements:
        new_elements = [item.strip() for item in elements_draft.split(",") if item.strip()]
        try:
            validate_elements(new_elements)
            old_elements = st.session_state.elements
            # Preserve cells whose row/column labels still exist.
            st.session_state.theta_values = {
                (a, b): st.session_state.theta_values.get((a, b), "")
                for a in new_elements for b in new_elements
            }
            st.session_state.phi_values = {
                (a, b): st.session_state.phi_values.get((a, b), "")
                for a in new_elements for b in new_elements
            }
            st.session_state.elements = new_elements
            st.session_state.pop("theta_editor", None)
            st.session_state.pop("phi_editor", None)
            st.success("Set updated. Existing values for unchanged elements were preserved.")
            st.rerun()
        except AlgebraError as exc:
            st.error(str(exc))

    elements = st.session_state.elements
    st.markdown("---")
    st.subheader("Edit operation tables")
    st.caption("Click a cell and type its result. Use Tab / Shift+Tab to move between cells. Each cell must contain an element from the set.")

    theta_col, phi_col = st.columns(2, gap="large")
    with theta_col:
        st.markdown("**θ operation table**")
        theta_df = st.data_editor(
            table_to_df(elements, st.session_state.theta_values),
            key="theta_editor",
            use_container_width=True,
            num_rows="fixed",
            height=min(420, 42 * (len(elements) + 1) + 10),
            column_config={c: st.column_config.TextColumn(str(c), help=f"θ(row, {c})") for c in elements},
        )
    with phi_col:
        st.markdown("**φ operation table**")
        phi_df = st.data_editor(
            table_to_df(elements, st.session_state.phi_values),
            key="phi_editor",
            use_container_width=True,
            num_rows="fixed",
            height=min(420, 42 * (len(elements) + 1) + 10),
            column_config={c: st.column_config.TextColumn(str(c), help=f"φ(row, {c})") for c in elements},
        )

    # Persist the current editor output on every rerun, so navigation and other
    # controls do not discard values already entered by the user.
    theta = df_to_table(theta_df, elements)
    phi = df_to_table(phi_df, elements)
    st.session_state.theta_values = theta
    st.session_state.phi_values = phi
    current_signature = (tuple(elements), tuple(sorted(theta.items())), tuple(sorted(phi.items())))
    if st.session_state.get("validated_signature") != current_signature:
        st.session_state.pop("workspace_validation", None)
    # The signature is recorded only when the user explicitly validates.
    if st.session_state.get("workspace_validation") is not None:
        st.session_state.validated_signature = current_signature

    st.markdown("---")
    st.markdown("**Table status**")
    status_left, status_right = st.columns(2)
    with status_left:
        st.caption("θ operation")
        theta_filled = sum(bool(str(v).strip()) for v in theta.values())
        st.caption(f"{theta_filled} / {len(elements) ** 2} cells entered")
    with status_right:
        st.caption("φ operation")
        phi_filled = sum(bool(str(v).strip()) for v in phi.values())
        st.caption(f"{phi_filled} / {len(elements) ** 2} cells entered")

    if st.button("Validate both operation tables", key="validate_workspace"):
        theta_errors = validate_operation(elements, theta, "theta")
        phi_errors = validate_operation(elements, phi, "phi")
        st.session_state.workspace_validation = {"theta": theta_errors, "phi": phi_errors}
        st.session_state.validated_signature = (tuple(elements), tuple(sorted(theta.items())), tuple(sorted(phi.items())))
    validation = st.session_state.get("workspace_validation")
    if validation is not None:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**θ validation**")
            if validation["theta"]:
                for error in validation["theta"]:
                    st.error(error)
            else:
                st.success("θ is a complete and closed binary operation.")
        with c2:
            st.markdown("**φ validation**")
            if validation["phi"]:
                for error in validation["phi"]:
                    st.error(error)
            else:
                st.success("φ is a complete and closed binary operation.")

    algebra_name = st.text_input("Name this algebra to save it", "My algebra", key="algebra_name")
    if st.button("Save algebra configuration", type="primary"):
        theta_errors = validate_operation(elements, theta, "theta")
        phi_errors = validate_operation(elements, phi, "phi")
        if theta_errors or phi_errors:
            st.error("Fix validation errors before saving.")
        else:
            save_algebra(current_user, algebra_name.strip(), elements, theta, phi)
            st.success("Algebra configuration saved to your account.")

with tabs[1]:
    st.subheader("Automatic operation table generator")
    n = st.number_input("Modulus n", min_value=1, max_value=20, value=3, step=1)
    op_choice = st.selectbox(
        "Operation",
        ["Addition modulo n", "Subtraction modulo n", "Multiplication modulo n"]
    )
    op_key = {
        "Addition modulo n": "add",
        "Subtraction modulo n": "subtract",
        "Multiplication modulo n": "multiply"
    }[op_choice]
    generated_elements = [str(i) for i in range(int(n))]
    generated = generate_operation_table(generated_elements, op_key, int(n))
    st.dataframe(table_to_df(generated_elements, generated), use_container_width=True)
    target = st.selectbox("Apply generated table to", ["θ", "φ"])
    if st.button("Use generated table in workspace"):
        st.session_state.pending_generated = {
            "elements": generated_elements,
            "table": generated,
            "target": target
        }
        st.rerun()

with tabs[2]:
    st.subheader("Automatic structure detection")
    theta_errors = validate_operation(elements, theta, "theta")
    phi_errors = validate_operation(elements, phi, "phi")
    if theta_errors or phi_errors:
        st.info("Structure detection is ready once both tables are filled and validated. No errors are reported for an untouched workspace.")
    else:
        left, right = st.columns(2)
        with left:
            st.markdown("### θ as a single operation")
            tp = check_properties(elements, theta)
            st.info(detect_structure(tp))
            show_property("Commutativity", tp["commutativity"])
            show_property("Associativity", tp["associativity"])
            show_property("Idempotence", tp["idempotence"])
            show_property("Left cancellation", tp["left_cancellation"])
            show_property("Right cancellation", tp["right_cancellation"])
            st.write("Left identities:", tp["left_identity"])
            st.write("Right identities:", tp["right_identity"])
            st.write("Two-sided identities:", tp["identities"])
            st.write("Two-sided inverse candidates:", tp["inverses"])
        with right:
            st.markdown("### φ as a single operation")
            pp = check_properties(elements, phi)
            st.info(detect_structure(pp))
            show_property("Commutativity", pp["commutativity"])
            show_property("Associativity", pp["associativity"])
            show_property("Idempotence", pp["idempotence"])
            show_property("Left cancellation", pp["left_cancellation"])
            show_property("Right cancellation", pp["right_cancellation"])
            st.write("Left identities:", pp["left_identity"])
            st.write("Right identities:", pp["right_identity"])
            st.write("Two-sided identities:", pp["identities"])
            st.write("Two-sided inverse candidates:", pp["inverses"])

        st.markdown("---")
        st.markdown("### Pair structure: (L, θ, φ)")
        pair = detect_pair_structure(elements, theta, phi)
        st.header(pair["classification"])
        if pair.get("reasons"):
            for reason in pair["reasons"]:
                st.write("•", reason)
        if pair.get("distributivity", {}).get("valid"):
            show_property("Left distributivity", pair["distributivity"]["left"])
            show_property("Right distributivity", pair["distributivity"]["right"])
        if pair.get("zero") is not None:
            st.write("Additive zero:", pair["zero"])
            st.write("Multiplicative identity:", pair.get("one"))
            st.write("Nonzero multiplicative inverses:", pair.get("nonzero_multiplicative_inverses", {}))

with tabs[3]:
    STANDARD_THEOREMS = [
        {"name": "Commutativity of θ", "vars": 2, "lhs": "theta(x,y)", "rhs": "theta(y,x)"},
        {"name": "Commutativity of φ", "vars": 2, "lhs": "phi(x,y)", "rhs": "phi(y,x)"},
        {"name": "Associativity of θ", "vars": 3, "lhs": "theta(x,theta(y,z))", "rhs": "theta(theta(x,y),z)"},
        {"name": "Associativity of φ", "vars": 3, "lhs": "phi(x,phi(y,z))", "rhs": "phi(phi(x,y),z)"},
        {"name": "Left Distributive", "vars": 3, "lhs": "theta(x,phi(y,z))", "rhs": "phi(theta(x,y),theta(x,z))"},
        {"name": "Right Distributive", "vars": 3, "lhs": "theta(phi(x,y),z)", "rhs": "phi(theta(x,z),theta(y,z))"},
    ]
    st.subheader("Built-in theorem algorithms")
    st.caption("These six original algorithms are always available and cannot be deleted. Your saved custom algorithms appear below.")
    standard_names = [item["name"] for item in STANDARD_THEOREMS]
    selected_standard = st.selectbox("Choose a built-in theorem", standard_names, key="builtin_theorem_choice")
    if st.button("Verify built-in theorem", key="verify_builtin", type="secondary"):
        chosen = next(item for item in STANDARD_THEOREMS if item["name"] == selected_standard)
        try:
            if validate_operation(elements, theta, "theta") or validate_operation(elements, phi, "phi"):
                st.warning("Fill both operation tables with valid results before verification.")
            else:
                result = verify_theorem(chosen["lhs"], chosen["rhs"], chosen["vars"], elements, theta, phi)
                st.metric("Cases passed", f'{result["passed"]}/{result["total"]}')
                if result["verified"]:
                    st.success(f'{chosen["name"]} holds for every assignment.')
                else:
                    st.error(f'{chosen["name"]} fails in {result["failed"]} case(s).')
                for row in result["results"]:
                    with st.expander(f'Assignment: {row["variables"]} — {"PASS" if row["passed"] else "FAIL"}'):
                        st.write("LHS steps")
                        for step in row["lhs_steps"]:
                            st.write(f'{step["expression"]} = {step["result"]}')
                        st.write("RHS steps")
                        for step in row["rhs_steps"]:
                            st.write(f'{step["expression"]} = {step["result"]}')
                        if not row["passed"]:
                            st.error("Counterexample: " + str(row["variables"]))
        except AlgebraError as exc:
            st.error(str(exc))

    st.markdown("---")
    st.subheader("Create and verify a custom theorem")
    theorem_name = st.text_input("Theorem / algorithm name", key="new_thm_name")
    variable_count = st.selectbox("Number of variables", [2, 3], key="new_var_count")
    lhs = st.text_input("LHS", placeholder="theta(x,theta(y,z))", key="new_lhs")
    rhs = st.text_input("RHS", placeholder="theta(theta(x,y),z)", key="new_rhs")
    st.caption('Syntax: theta(x,y), phi(x,phi(y,z)). Variables: x, y, z. You can also use quoted constants such as theta("0", x).')
    if st.button("Verify theorem and show proof", type="primary"):
        try:
            if validate_operation(elements, theta, "theta") or validate_operation(elements, phi, "phi"):
                st.error("Both operation tables must be complete and closed.")
            else:
                result = verify_theorem(lhs, rhs, variable_count, elements, theta, phi)
                st.metric("Cases passed", f'{result["passed"]}/{result["total"]}')
                if result["verified"]:
                    st.success("The theorem holds for every assignment in this finite set.")
                else:
                    st.error(f'The theorem fails in {result["failed"]} case(s).')
                for row in result["results"]:
                    with st.expander(f'Assignment: {row["variables"]} — {"PASS" if row["passed"] else "FAIL"}'):
                        st.markdown("**LHS evaluation**")
                        for step in row["lhs_steps"]:
                            st.write(f'{step["expression"]} = {step["result"]}')
                        st.write("LHS final value:", row["lhs"])
                        st.markdown("**RHS evaluation**")
                        for step in row["rhs_steps"]:
                            st.write(f'{step["expression"]} = {step["result"]}')
                        st.write("RHS final value:", row["rhs"])
                        if not row["passed"]:
                            st.error("Counterexample: " + str(row["variables"]))
                if theorem_name.strip():
                    save_theorem(current_user, theorem_name.strip(), variable_count, lhs.strip(), rhs.strip())
                    st.success("Theorem saved in the persistent library.")
        except AlgebraError as exc:
            st.error(str(exc))

    st.markdown("---")
    st.subheader("Your saved theorem / algorithm library")
    saved = list_theorems(current_user)
    if not saved:
        st.info("No saved theorems yet.")
    else:
        for item in saved:
            with st.expander(f'{item["name"]} — {item["lhs"]} = {item["rhs"]}'):
                st.write("Variables:", item["variable_count"])
                st.code(f'{item["lhs"]} = {item["rhs"]}')
                if st.button("Delete theorem", key=f'del_thm_{item["id"]}'):
                    delete_theorem(current_user, item["id"])
                    st.rerun()

with tabs[4]:
    st.subheader(f"Saved algebra configurations — {current_user}")
    saved_algebras = list_algebras(current_user)
    if not saved_algebras:
        st.info("No saved algebras yet. Save one from Workspace.")
    for item in saved_algebras:
        with st.expander(item["name"]):
            st.write("Set:", item["elements"])
            st.dataframe(table_to_df(item["elements"], item["theta"]))
            st.write("φ table")
            st.dataframe(table_to_df(item["elements"], item["phi"]))
            if st.button("Delete saved algebra", key=f'del_alg_{item["id"]}'):
                delete_algebra(current_user, item["id"])
                st.rerun()
