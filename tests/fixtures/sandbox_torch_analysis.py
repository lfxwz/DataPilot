import torch


def analyze(data):
    torch.manual_seed(42)
    x = torch.tensor([[row["x"]] for row in data], dtype=torch.float32)
    y = torch.tensor([[row["y"]] for row in data], dtype=torch.float32)
    model = torch.nn.Sequential(torch.nn.Linear(1, 4), torch.nn.ReLU(), torch.nn.Linear(4, 1))
    optimizer = torch.optim.Adam(model.parameters(), lr=0.03)
    loss_function = torch.nn.MSELoss()
    initial_loss = float(loss_function(model(x), y).item())
    for _ in range(20):
        optimizer.zero_grad()
        loss = loss_function(model(x), y)
        loss.backward()
        optimizer.step()
    final_loss = float(loss_function(model(x), y).item())
    return {
        "analysis_type": "neural_network_smoke_test",
        "summary_metrics": {"initial_mse": initial_loss, "final_mse": final_loss},
        "findings": ["A small CPU neural network completed bounded training."],
        "diagnostics": {"row_count": len(data), "epochs": 20, "seed": 42},
        "limitations": ["This fixed smoke test is not a production predictive model."],
    }
