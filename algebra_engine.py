import ast
from itertools import product


class AlgebraError(Exception):
    pass


def validate_elements(elements):
    if not elements:
        raise AlgebraError("The set must contain at least one element.")
    if len(elements) != len(set(elements)):
        raise AlgebraError("Set elements must be unique.")
    if any(not isinstance(x, str) or not x.strip() for x in elements):
        raise AlgebraError("Set elements must be non-empty strings.")


def validate_operation(elements, table, operation_name="operation"):
    errors = []
    expected = set(product(elements, repeat=2))
    actual = set(table)

    for key in sorted(expected - actual):
        errors.append(f"{operation_name}: missing entry for {key}")

    for key in sorted(actual - expected):
        errors.append(f"{operation_name}: unexpected entry for {key}")

    for (a, b), result in table.items():
        if not str(result).strip():
            errors.append(f"{operation_name}: missing value for ({a}, {b}).")
        elif result not in elements:
            errors.append(
                f"{operation_name}: closure violation: "
                f"{operation_name}({a},{b}) = {result}, which is not in the set."
            )
    return errors


def generate_operation_table(elements, operation, modulus=None):
    """Generate a binary operation table over residues 0,...,n-1."""
    if operation not in {"add", "subtract", "multiply"}:
        raise AlgebraError("Unsupported generated operation.")
    if not modulus or modulus < 1:
        raise AlgebraError("Modulus must be a positive integer.")

    expected = [str(i) for i in range(modulus)]
    if list(elements) != expected:
        raise AlgebraError(
            "Generated modular tables require the set 0,1,...,n-1."
        )

    fn = {
        "add": lambda a, b: (a + b) % modulus,
        "subtract": lambda a, b: (a - b) % modulus,
        "multiply": lambda a, b: (a * b) % modulus,
    }[operation]

    return {
        (str(a), str(b)): str(fn(a, b))
        for a in range(modulus)
        for b in range(modulus)
    }


def _property_result(holds, counterexample=None):
    return {"holds": holds, "counterexample": counterexample}


def check_properties(elements, table):
    errors = validate_operation(elements, table)
    if errors:
        return {"valid": False, "errors": errors}

    comm_ce = None
    for a, b in product(elements, repeat=2):
        if table[(a, b)] != table[(b, a)]:
            comm_ce = {"a": a, "b": b, "ab": table[(a, b)], "ba": table[(b, a)]}
            break

    assoc_ce = None
    for a, b, c in product(elements, repeat=3):
        left = table[(table[(a, b)], c)]
        right = table[(a, table[(b, c)])]
        if left != right:
            assoc_ce = {
                "a": a, "b": b, "c": c,
                "left": left, "right": right,
                "left_expression": f"({a}*{b})*{c}",
                "right_expression": f"{a}*({b}*{c})"
            }
            break

    idem_ce = next(
        ({"a": a, "aa": table[(a, a)]} for a in elements if table[(a, a)] != a),
        None
    )

    left_ids = [
        e for e in elements
        if all(table[(e, a)] == a for a in elements)
    ]
    right_ids = [
        e for e in elements
        if all(table[(a, e)] == a for a in elements)
    ]
    identities = [e for e in left_ids if e in right_ids]

    left_cancel_ce = None
    right_cancel_ce = None
    for a, b, c in product(elements, repeat=3):
        if table[(a, b)] == table[(a, c)] and b != c and left_cancel_ce is None:
            left_cancel_ce = {"a": a, "b": b, "c": c, "ab": table[(a,b)], "ac": table[(a,c)]}
        if table[(b, a)] == table[(c, a)] and b != c and right_cancel_ce is None:
            right_cancel_ce = {"a": a, "b": b, "c": c, "ba": table[(b,a)], "ca": table[(c,a)]}

    inverses = {}
    for e in identities:
        inverses[e] = {
            a: [
                b for b in elements
                if table[(a, b)] == e and table[(b, a)] == e
            ]
            for a in elements
        }

    has_identity = bool(identities)
    inverse_map = inverses[identities[0]] if has_identity else {}
    has_all_inverses = has_identity and all(inverse_map[a] for a in elements)

    return {
        "valid": True,
        "errors": [],
        "closure": True,
        "commutativity": _property_result(comm_ce is None, comm_ce),
        "associativity": _property_result(assoc_ce is None, assoc_ce),
        "idempotence": _property_result(idem_ce is None, idem_ce),
        "left_identity": left_ids,
        "right_identity": right_ids,
        "identities": identities,
        "left_cancellation": _property_result(left_cancel_ce is None, left_cancel_ce),
        "right_cancellation": _property_result(right_cancel_ce is None, right_cancel_ce),
        "inverses": inverse_map,
        "has_all_inverses": bool(has_all_inverses),
    }


def detect_structure(properties):
    if not properties.get("valid", False):
        return "Invalid operation"
    if not properties["associativity"]["holds"]:
        return "Magma (not a semigroup)"
    if not properties["identities"]:
        return "Semigroup"
    if not properties["has_all_inverses"]:
        return "Monoid"
    if properties["commutativity"]["holds"]:
        return "Abelian group"
    return "Group"


def check_distributivity(elements, addition, multiplication):
    errors = (
        validate_operation(elements, addition, "addition")
        + validate_operation(elements, multiplication, "multiplication")
    )
    if errors:
        return {"valid": False, "errors": errors}

    left_ce = None
    right_ce = None
    for a, b, c in product(elements, repeat=3):
        lhs = multiplication[(a, addition[(b, c)])]
        rhs = addition[(multiplication[(a, b)], multiplication[(a, c)])]
        if lhs != rhs and left_ce is None:
            left_ce = {"a": a, "b": b, "c": c, "lhs": lhs, "rhs": rhs}

        lhs = multiplication[(addition[(a, b)], c)]
        rhs = addition[(multiplication[(a, c)], multiplication[(b, c)])]
        if lhs != rhs and right_ce is None:
            right_ce = {"a": a, "b": b, "c": c, "lhs": lhs, "rhs": rhs}

    return {
        "valid": True,
        "left": _property_result(left_ce is None, left_ce),
        "right": _property_result(right_ce is None, right_ce),
    }


def detect_pair_structure(elements, addition, multiplication):
    """Classify common finite ring/field conditions.

    Convention: addition is the additive operation; multiplication is the
    multiplicative operation. A field is a commutative ring with 1 != 0
    in which every nonzero element has a multiplicative inverse.
    """
    add_p = check_properties(elements, addition)
    mul_p = check_properties(elements, multiplication)
    dist = check_distributivity(elements, addition, multiplication)

    result = {
        "addition_properties": add_p,
        "multiplication_properties": mul_p,
        "distributivity": dist,
        "classification": "Not a ring",
        "reasons": []
    }

    if not add_p.get("valid") or not mul_p.get("valid") or not dist.get("valid"):
        result["reasons"].append("One or both operation tables are invalid.")
        return result

    additive_group = (
        add_p["associativity"]["holds"]
        and bool(add_p["identities"])
        and add_p["commutativity"]["holds"]
        and add_p["has_all_inverses"]
    )
    multiplicative_associative = mul_p["associativity"]["holds"]
    distributive = dist["left"]["holds"] and dist["right"]["holds"]

    if not additive_group:
        result["reasons"].append(
            "Addition must form an abelian group."
        )
        return result
    if not multiplicative_associative:
        result["reasons"].append(
            "Multiplication must be associative."
        )
        return result
    if not distributive:
        result["reasons"].append(
            "Both distributive laws must hold."
        )
        return result

    result["classification"] = "Ring (possibly without multiplicative identity)"
    one_candidates = mul_p["identities"]
    zero = add_p["identities"][0]
    if one_candidates:
        one = one_candidates[0]
        result["zero"] = zero
        result["one"] = one
        if one == zero:
            result["reasons"].append("Multiplicative identity equals additive zero.")
            return result

        nonzero = [a for a in elements if a != zero]
        nonzero_inverses = {
            a: [
                b for b in elements
                if b != zero
                and multiplication[(a, b)] == one
                and multiplication[(b, a)] == one
            ]
            for a in nonzero
        }
        all_nonzero_invertible = all(nonzero_inverses[a] for a in nonzero)
        mul_commutative = mul_p["commutativity"]["holds"]

        if all_nonzero_invertible and mul_commutative:
            result["classification"] = "Field"
        elif all_nonzero_invertible:
            result["classification"] = "Division ring"
        elif mul_commutative:
            result["classification"] = "Commutative ring with identity"
        else:
            result["classification"] = "Ring with identity"
        result["nonzero_multiplicative_inverses"] = nonzero_inverses
    else:
        result["reasons"].append("No multiplicative identity was found.")

    return result


def parse_expression(expression, variable_names):
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise AlgebraError(f"Invalid expression syntax: {exc.msg}") from exc

    allowed_variables = set(variable_names)
    allowed_functions = {"theta", "phi"}

    def validate(node):
        if isinstance(node, ast.Name):
            if node.id not in allowed_variables:
                raise AlgebraError(f"Unknown name: {node.id}")
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, str):
                raise AlgebraError("Only quoted string constants are supported.")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in allowed_functions:
                raise AlgebraError("Only theta(...) and phi(...) calls are allowed.")
            if len(node.args) != 2 or node.keywords:
                raise AlgebraError("Each binary operation needs exactly two positional arguments.")
            for arg in node.args:
                validate(arg)
        else:
            raise AlgebraError(
                f"Unsupported syntax: {type(node).__name__}. "
                "Use variables and nested theta()/phi() calls only."
            )

    validate(tree.body)
    return tree


def evaluate_expression(tree, values, theta, phi):
    steps = []

    def evaluate(node):
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise AlgebraError(f"No value supplied for variable {node.id}.")
            return values[node.id]

        if isinstance(node, ast.Constant):
            return str(node.value)

        if isinstance(node, ast.Call):
            a = evaluate(node.args[0])
            b = evaluate(node.args[1])
            operation = node.func.id
            table = theta if operation == "theta" else phi
            key = (a, b)
            if key not in table:
                raise AlgebraError(f"{operation}({a},{b}) is undefined.")
            result = table[key]
            symbol = "θ" if operation == "theta" else "φ"
            steps.append({
                "expression": f"{symbol}({a}, {b})",
                "result": result,
                "operation": operation
            })
            return result

        raise AlgebraError("Unsupported expression node.")

    return evaluate(tree.body), steps


def verify_theorem(lhs, rhs, variable_count, elements, theta, phi):
    if variable_count not in (2, 3):
        raise AlgebraError("The theorem must use two or three variables.")

    names = ["x", "y", "z"][:variable_count]
    lhs_tree = parse_expression(lhs, names)
    rhs_tree = parse_expression(rhs, names)
    results = []

    for combo in product(elements, repeat=variable_count):
        values = dict(zip(names, combo))
        lhs_value, lhs_steps = evaluate_expression(lhs_tree, values, theta, phi)
        rhs_value, rhs_steps = evaluate_expression(rhs_tree, values, theta, phi)
        results.append({
            "variables": values,
            "lhs": lhs_value,
            "rhs": rhs_value,
            "lhs_steps": lhs_steps,
            "rhs_steps": rhs_steps,
            "passed": lhs_value == rhs_value
        })

    passed = sum(1 for row in results if row["passed"])
    return {
        "verified": passed == len(results),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results
    }
