"""
data_json has 
0. refs        : list of {ref_id, ann_id, box, image_id, split, category_id, sent_ids}
1. images      : list of {image_id, ref_ids, ann_ids, file_name, width, height, h5_id}
2. anns        : list of {ann_id, category_id, image_id, box, h5_id}
3. sentences   : list of {sent_id, tokens, h5_id}
4: word_to_ix  : word->ix
5: cat_to_ix   : cat->ix
6: label_length: L
Note, box in [xywh] format
data_h5 has
/labels is (M, max_length) uint32 array of encoded labels, zeros padded
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os.path as osp
import numpy as np
import h5py
import json
import random
from pytorch_pretrained_bert import BertTokenizer

class Loader(object):

    def __init__(self, data_json, sub_obj_wds, similarity, data_h5=None, data_emb=None):
        print('Loader loading similarity file:', similarity)
        self.similarity_info = json.load(open(similarity))
        self.similarity = self.similarity_info['sim']
        # load the json file which contains info about the dataset
        print('Loader loading subject and object words:', sub_obj_wds)
        self.sub_obj_wds_info = json.load(open(sub_obj_wds))
        self.sub_obj_wds = self.sub_obj_wds_info['sub_obj_wds']
        print('Loader loading data.json: ', data_json)
        self.info = json.load(open(data_json))
        self.word_to_ix = self.info['word_to_ix']
        self.ix_to_word = {ix: wd for wd, ix in self.word_to_ix.items()}
        print('vocab size is ', self.vocab_size)
        self.cat_to_ix = self.info['cat_to_ix']
        self.ix_to_cat = {ix: cat for cat, ix in self.cat_to_ix.items()}
        print('object cateogry size is ', len(self.ix_to_cat))
        self.images = self.info['images']
        self.anns = self.info['anns']
        self.refs = self.info['refs']
        self.sentences = self.info['sentences']
        print('we have %s images.' % len(self.images))
        print('we have %s anns.' % len(self.anns))
        print('we have %s refs.' % len(self.refs))
        print('we have %s sentences.' % len(self.sentences))
        print('label_length is ', self.label_length)

        # construct mapping
        self.Refs = {ref['ref_id']: ref for ref in self.refs}
        self.Images = {image['image_id']: image for image in self.images}
        self.Anns = {ann['ann_id']: ann for ann in self.anns}
        self.Sentences = {sent['sent_id']: sent for sent in self.sentences}
        self.annToRef = {ref['ann_id']: ref for ref in self.refs}
        self.sentToRef = {sent_id: ref for ref in self.refs for sent_id in ref['sent_ids']}

        # read data_h5 if exists
        self.data_h5 = None
        if data_h5 is not None:
            print('Loader loading data.h5: ', data_h5)
            self.data_h5 = h5py.File(data_h5, 'r')
            assert self.data_h5['labels'].shape[0] == len(self.sentences), 'label.shape[0] not match sentences'
            assert self.data_h5['labels'].shape[1] == self.label_length, 'label.shape[1] not match label_length'

        self.data_emb = None
        if data_emb is not None:
            print('Loader loading data.h5: ', data_emb)
            self.data_emb = h5py.File(data_emb, 'r')
            assert self.data_emb['labels'].shape[0] == len(self.sentences), 'label.shape[0] not match sentences'
            # assert self.data_emb['labels'].shape[1] == self.label_length, 'label.shape[1] not match label_length'

        # self.tokenizer = BertTokenizer.from_pretrained('bert-large-uncased')

    # @property装饰器负责把一个方法变成属性调用,广泛应用在类的定义中，可以让调用者写出简短的代码，同时保证对参数进行必要的检查
    @property
    def vocab_size(self):
        # len(self.word_to_ix) == 1999
        return len(self.word_to_ix)

    @property
    def label_length(self):
        return self.info['label_length']

    @property
    def sent_to_Ref(self, sent_id):
        return self.sent_to_Ref(sent_id)

    # 将sentecne中的string通过vocab转化为id
    def encode_labels(self, sent_str_list):
        """Input:
        sent_str_list: list of n sents in string format
        return int32 (n, label_length) zeros padded in end
        """
        num_sents = len(sent_str_list)
        L = np.zeros((num_sents, self.label_length), dtype=np.int32)
        for i, sent_str in enumerate(sent_str_list):
            tokens = sent_str.split()
            for j, w in enumerate(tokens):
              if j < self.label_length:
                  L[i, j] = self.word_to_ix[w] if w in self.word_to_ix else self.word_to_ix['<UNK>']
        return L

    # 将sentence中的id转化为string
    def decode_labels(self, labels):
        """
        labels: int32 (n, label_length) zeros padded in end
        return: list of sents in string format
        """
        decoded_sent_strs = []
        num_sents = labels.shape[0]
        for i in range(num_sents):
            label = labels[i].tolist()
            sent_str = ' '.join([self.ix_to_word[int(i)] for i in label if i != 0])
            decoded_sent_strs.append(sent_str)
        return decoded_sent_strs

    # 一个ref_id对应多个sent_id, 根据ref_id得到转化后的sentence
    def fetch_label(self, ref_id, num_sents):
        """
        return: int32 (num_sents, label_length) and picked_sent_ids
        """
        ref = self.Refs[ref_id]
        sent_ids = list(ref['sent_ids'])  # copy in case the raw list is changed
        seq = []
        # 将每个ref中的sent个数设置成一样的，如果个数少于num_sents,则将少的部分用已有的sent随机填充，否则，选择前num_sent个sentences
        if len(sent_ids) < num_sents:
            append_sent_ids = [random.choice(sent_ids) for _ in range(num_sents - len(sent_ids))]
            sent_ids += append_sent_ids
        else:
            sent_ids = sent_ids[:num_sents]
        assert len(sent_ids) == num_sents
        # fetch label
        for sent_id in sent_ids:
            sent_h5_id = self.Sentences[sent_id]['h5_id']
            seq += [self.data_h5['labels'][sent_h5_id, :]]
        seq = np.vstack(seq)
        return seq, sent_ids

    # 根据sent_id得到转化后的sentences
    def fetch_seq(self, sent_id):
        # return int32 (label_length, )
        sent_h5_id = self.Sentences[sent_id]['h5_id']
        seq = self.data_h5['labels'][sent_h5_id, :]
        return seq
    #
    # def fetch_seq_bert(self, sent_id):
    #     tokens = self.Sentences[sent_id]['tokens']
    #     seq = self.tokenizer.convert_tokens_to_ids(tokens)
    #     seq = np.array(seq)
    #     return seq

    def fetch_emb(self, sent_id):
        # return int32 (label_length, )
        sent_h5_id = self.Sentences[sent_id]['h5_id']
        emb = self.data_emb['labels'][sent_h5_id, 0, :]
        return emb

