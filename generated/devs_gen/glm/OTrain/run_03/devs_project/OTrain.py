from xdevs.models import Atomic, Coupled, Port

from .OTrain_libs.TrainSystem import TrainSystem


class OTrain(Coupled):
    """Root coupled model for the O-Train simulation. It encapsulates the entire TrainSystem logic, which manages train movement, passenger generation, station queues, and train alighting. It acts as a container for the single atomic child `TrainSystem` and does not perform any I/O or state transitions itself."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Instantiate the single atomic child TrainSystem
        # The locked contract specifies no additional arguments for this coupled model's __init__
        # other than name and parent. The TrainSystem also only takes name and parent.
        train_system = TrainSystem(
            name="TrainSystem",
            parent=self,
        )
        self.add_component(train_system)