#!/usr/bin/env bash

wget https://storage.googleapis.com/xlnet/released_models/cased_L-12_H-768_A-12.zip
unzip cased_L-12_H-768_A-12.zip

mv cased_L-12_H-768_A-12 xlnet_pretrain
rm cased_L-12_H-768_A-12.zip