from rdkit import Chem
from torch_geometric.data import Data, Dataset, InMemoryDataset
import copy
import lzma
import networkx as nx
import numpy as np
import pandas as pd
import pickle
import torch
from torch_geometric.data.separate import separate


def atom_features(atom):
    HYB_list = [Chem.rdchem.HybridizationType.S, Chem.rdchem.HybridizationType.SP,
                Chem.rdchem.HybridizationType.SP2, Chem.rdchem.HybridizationType.SP3,
                Chem.rdchem.HybridizationType.SP3D, Chem.rdchem.HybridizationType.SP3D2,
                Chem.rdchem.HybridizationType.UNSPECIFIED, Chem.rdchem.HybridizationType.OTHER]
    return np.array(one_of_k_encoding_unk(atom.GetSymbol(),
                                          ['C', 'N', 'O', 'S', 'F', 'Si', 'P', 'Cl', 'Br', 'Mg', 'Na', 'Ca', 'Fe', 'As',
                                           'Al', 'I', 'B', 'V', 'K', 'Tl', 'Yb', 'Sb', 'Sn', 'Ag', 'Pd', 'Co', 'Se',
                                           'Ti', 'Zn', 'H', 'Li', 'Ge', 'Cu', 'Au', 'Ni', 'Cd', 'In', 'Mn', 'Zr', 'Cr',
                                           'Pt', 'Hg', 'Pb', 'Sm', 'Tc', 'Gd', 'Unknown']) +
                    one_of_k_encoding(atom.GetDegree(), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) +
                    one_of_k_encoding_unk(atom.GetTotalNumHs(), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) +
                    one_of_k_encoding_unk(atom.GetExplicitValence(), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) +
                    one_of_k_encoding_unk(atom.GetImplicitValence(), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) +
                    one_of_k_encoding(atom.GetFormalCharge(), [-4, -3, -2, -1, 0, 1, 2, 3, 4]) +
                    one_of_k_encoding(atom.GetHybridization(), HYB_list) +
                    [atom.GetIsAromatic()])


def one_of_k_encoding(x, allowable_set):
    if x not in allowable_set:
        raise Exception("input {0} not in allowable set{1}:".format(x, allowable_set))
    return list(map(lambda s: x == s, allowable_set))


def one_of_k_encoding_unk(x, allowable_set):
    if x not in allowable_set:
        x = allowable_set[-1]
    return list(map(lambda s: x == s, allowable_set))


def smile_to_graph(smile):
    mol = Chem.MolFromSmiles(smile)
    c_size = mol.GetNumAtoms()

    features = []
    for atom in mol.GetAtoms():
        feature = atom_features(atom)
        features.append(feature)

    features = np.array(features)

    edges = []
    edge_type = []
    for bond in mol.GetBonds():
        edges.append([bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()])
        edge_type.append(bond.GetBondTypeAsDouble())
    g = nx.Graph(edges).to_directed()
    edge_index = []
    for e1, e2 in g.edges:
        edge_index.append([e1, e2])

    if not edge_index:
        edge_index = []
    else:
        edge_index = np.array(edge_index).transpose(1, 0)

    return c_size, features, edge_index, edge_type


class Dataset(InMemoryDataset):
    def __init__(self, transform=None, pre_transform=None):
        super(Dataset, self).__init__(transform, pre_transform)

        data_list = []
        smiles = pd.read_excel('data/drug_SMILES.xlsx', header=None, engine='openpyxl')[1].tolist()

        for i in range(750):
            c_size, features, edge_index, edge_type = smile_to_graph(smiles[i])
            data = Data(x=torch.Tensor(features), edge_index=torch.LongTensor(edge_index))
            data.__setitem__('edge_type', torch.FloatTensor(edge_type * 2).int().flatten())
            data.__setitem__('x_index', torch.LongTensor([0]))
            data.__setitem__('c_size', torch.LongTensor([c_size]))
            data.index = [i]

            data_list.append(data)

        if self.pre_filter is not None:
            data_list = [data for data in data_list if self.pre_filter(data)]

        if self.pre_transform is not None:
            data_list = [self.pre_transform(data) for data in data_list]

        self.data, self.slices = self.collate(data_list)

        with open('data/Text_similarity_five.pkl', 'rb') as f:
            self.w = torch.from_numpy(pickle.load(f)).float()

        with lzma.open('data/drug_target.xz', 'rb') as f:
            self.z = pickle.load(f)

        with open('data/drug_side.pkl', 'rb') as f:
            self.y = torch.from_numpy(pickle.load(f)).float()


    def len_features(self):
        return self.data.x.shape[1], self.w.shape[1], self.z.shape[1]

    def get(self, index):
        if not hasattr(self, '_data_list') or self._data_list is None:
            self._data_list = self.len() * [None]

        elif self._data_list[index] is not None:
            x = copy.copy(self._data_list[index])
            w = self.w[index]
            z = self.z[index]
            y = self.y[index]

            return index, (x, w, z), y


        x = separate(
            cls=self.data.__class__,
            batch=self.data,
            idx=index,
            slice_dict=self.slices,
            decrement=False,
        )

        self._data_list[index] = copy.copy(x)
        w = self.w[index]
        z = self.z[index]
        y = self.y[index]

        return index, (x, w, z), y
