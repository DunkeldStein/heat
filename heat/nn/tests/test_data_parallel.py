import heat as ht
import torch
import unittest

import heat.nn.functional as F


class TestDataParallel(unittest.TestCase):
    def test_data_parallel(self):
        with self.assertRaises(TypeError):
            ht.utils.data.datatools.DataLoader("asdf")

        class TestModel(ht.nn.Module):
            def __init__(self):
                super(TestModel, self).__init__()
                # 1 input image channel, 6 output channels, 3x3 square convolution
                # kernel
                self.conv1 = ht.nn.Conv2d(1, 6, 3)
                self.conv2 = ht.nn.Conv2d(6, 16, 3)
                # an affine operation: y = Wx + b
                self.fc1 = ht.nn.Linear(16 * 6 * 6, 120)  # 6*6 from image dimension
                self.fc2 = ht.nn.Linear(120, 84)
                self.fc3 = ht.nn.Linear(84, 10)

            def forward(self, x):
                # Max pooling over a (2, 2) window
                x = self.conv1(x)
                x = F.max_pool2d(F.relu(x), (2, 2))
                # If the size is a square you can only specify a single number
                x = F.max_pool2d(F.relu(self.conv2(x)), 2)
                x = x.view(-1, self.num_flat_features(x))
                x = F.relu(self.fc1(x))
                x = F.relu(self.fc2(x))
                x = self.fc3(x)
                return x

            def num_flat_features(self, x):
                size = x.size()[1:]  # all dimensions except the batch dimension
                num_features = 1
                for s in size:
                    num_features *= s
                return num_features

        # create model and move it to GPU with id rank
        model = TestModel()
        optimizer = ht.optim.SGD(model.parameters(), lr=0.001)
        with self.assertRaises(TypeError):
            ht.optim.dp_optimizer.DataParallelOptimizer(optimizer, "asdf")
        dp_optimizer = ht.optim.dp_optimizer.DataParallelOptimizer(optimizer, True)

        ht.random.seed(1)
        torch.random.manual_seed(1)

        labels = torch.randn(10, device=ht.get_device().torch_device)
        data = ht.random.rand(2 * ht.MPI_WORLD.size, 1, 32, 32, split=0)
        dataset = ht.utils.data.datatools.Dataset(data)
        dataloader = ht.utils.data.datatools.DataLoader(dataset=dataset, batch_size=2)
        ht_model = ht.nn.DataParallel(
            model, data.comm, dp_optimizer, blocking_parameter_updates=True
        )

        loss_fn = torch.nn.MSELoss()
        for _ in range(2):
            for data in dataloader:
                self.assertEqual(data.shape[0], 2)
                dp_optimizer.zero_grad()
                ht_outputs = ht_model(data)
                loss_fn(ht_outputs, labels).backward()
                dp_optimizer.step()

            for p in ht_model.parameters():
                p0dim = p.shape[0]
                hld = ht.resplit(ht.array(p, is_split=0))._DNDarray__array
                hld_list = [hld[i * p0dim : (i + 1) * p0dim] for i in range(ht.MPI_WORLD.size - 1)]
                for i in range(1, len(hld_list)):
                    self.assertTrue(torch.all(hld_list[0] == hld_list[i]))

        model = TestModel()
        optimizer = ht.optim.SGD(model.parameters(), lr=0.001)
        dp_optimizer = ht.optim.dp_optimizer.DataParallelOptimizer(optimizer, False)

        ht.random.seed(1)
        torch.random.manual_seed(1)

        labels = torch.randn(10, device=ht.get_device().torch_device)
        data = ht.random.rand(2 * ht.MPI_WORLD.size, 1, 32, 32, split=0)
        dataset = ht.utils.data.datatools.Dataset(data)
        dataloader = ht.utils.data.datatools.DataLoader(dataset=dataset, batch_size=2)
        ht_model = ht.nn.DataParallel(
            model, data.comm, dp_optimizer, blocking_parameter_updates=False
        )

        loss_fn = torch.nn.MSELoss()
        for _ in range(2):
            for data in dataloader:
                self.assertEqual(data.shape[0], 2)
                dp_optimizer.zero_grad()
                ht_outputs = ht_model(data)
                loss_fn(ht_outputs, labels).backward()
                dp_optimizer.step()
            for p in ht_model.parameters():
                p0dim = p.shape[0]
                hld = ht.resplit(ht.array(p, is_split=0))._DNDarray__array
                hld_list = [hld[i * p0dim : (i + 1) * p0dim] for i in range(ht.MPI_WORLD.size - 1)]
                for i in range(1, len(hld_list)):
                    self.assertTrue(torch.all(hld_list[0] == hld_list[i]))
