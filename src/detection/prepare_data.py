from sklearn.model_selection import train_test_split
import os
import pandas as pd
import shutil
from tqdm import tqdm
from datetime import datetime
from PIL import Image
from joblib import Parallel, delayed
from src.category_utils import *
import matplotlib.pyplot as plt
import seaborn as sns
import yaml


def adjust_stratify_column(df, stratify_by: str, min_instances_per_class: int = 6):
    """Adjust the stratify column to ensure each class has at least 6 instances.

    Args:
        df: DataFrame to adjust.
        stratify_by: The name of the column to be used for stratification.

    Returns:
        DataFrame with an adjusted column for stratification.
    """
    # Créer une copie de la colonne de stratification
    new_stratify_col = df[stratify_by].copy()

    # Trouver les classes avec moins de 6 instances
    class_counts = new_stratify_col.value_counts()
    small_classes = class_counts[class_counts < min_instances_per_class].index
    # afficher si il y a des classes avec moins de 6 instances
    if len(small_classes) > 0:
        print(
            f" > {len(small_classes)} classes with less than {min_instances_per_class} instances > {list(small_classes)}")

    # Fusionner les petites classes dans une nouvelle catégorie
    new_stratify_col.loc[new_stratify_col.isin(small_classes)] = 'Other'

    # Ajouter la nouvelle colonne ajustée au DataFrame
    df['adjusted_stratify'] = new_stratify_col

    return df


def split_dataset(df, val_size=0.1, test_size=0.2, random_state=123, stratify_by=None, no_test_set=False):
    """Split dataset into train, validation, and test sets.

    Args:
        df: Dataframe to split.
        val_size: Size of the validation set.
        test_size: Size of the test set.
        random_state: Random state for reproducibility.
        stratify_by: Stratify by column name.

    Returns:
        Tuple of train, validation, and test sets.
    """
    df = df.copy()
    # Ensure stratify_by is a valid column
    if stratify_by not in df.columns:
        stratify_by = None

    # Utilisation de la fonction
    df = adjust_stratify_column(df, stratify_by=stratify_by)

    if no_test_set:
        # Splitting the dataset into training and validation sets
        train_df, val_df = train_test_split(
            df,
            test_size=val_size,
            random_state=random_state,
            stratify=df["adjusted_stratify"] if stratify_by else None
        )
        return train_df, val_df, None

    # Adjust val_size to reflect the proportion of the remaining dataset after test split
    val_size_adjusted = val_size / (1 - test_size)

    # Splitting the dataset into training + validation and test sets
    train_val_df, test_df = train_test_split(
        df,
        test_size=test_size,
        random_state=random_state,
        stratify=df["adjusted_stratify"] if stratify_by else None
    )

    # Splitting the training + validation set into training and validation sets
    train_df, val_df = train_test_split(
        train_val_df,
        test_size=val_size_adjusted,
        random_state=random_state,
        stratify=train_val_df["adjusted_stratify"] if stratify_by else None
    )

    return train_df, val_df, test_df


def process_image_group(object_group, new_dataset_path):
    orig_image_path = object_group[0]
    label_matrix = object_group[1][["cat_id", "x_center_norm", "y_center_norm", "width_norm", "height_norm"]].values
    image_name = object_group[1]["img_file"].values[0]

    # copy image
    new_image_path = os.path.join(new_dataset_path, "images", image_name)
    if not os.path.exists(os.path.dirname(new_image_path)):
        os.makedirs(os.path.dirname(new_image_path))
    shutil.copy(orig_image_path, new_image_path)

    # create label file (yolo format) .txt
    new_label_path = os.path.join(new_dataset_path, "labels", os.path.splitext(image_name)[0] + ".txt")
    if not os.path.exists(os.path.dirname(new_label_path)):
        os.makedirs(os.path.dirname(new_label_path))

    # print(" > new_label_path: ", new_label_path)
    with open(new_label_path, "w", encoding="utf-8") as f:
        for label in label_matrix:
            f.write("{} {} {} {} {}\n".format(int(label[0]), float(label[1]), float(label[2]), float(label[3]),
                                              float(label[4])))


def process_images(df, new_dataset_path, df_name):
    object_groups = df.groupby("path")
    for object_group in tqdm(object_groups, desc=f"Processing {df_name} dataset"):
        process_image_group(object_group, os.path.join(new_dataset_path, df_name))


def process_images_parallel(df, new_dataset_path, df_name, n_jobs=-1):
    # create folders
    if not os.path.exists(os.path.join(new_dataset_path, df_name, "images")):
        os.makedirs(os.path.join(new_dataset_path, df_name, "images"))
    if not os.path.exists(os.path.join(new_dataset_path, df_name, "labels")):
        os.makedirs(os.path.join(new_dataset_path, df_name, "labels"))

    object_groups = df.groupby("path")
    Parallel(n_jobs=n_jobs)(
        delayed(process_image_group)(object_group, os.path.join(new_dataset_path, df_name)) for object_group in
        tqdm(object_groups, desc=f"Processing {df_name} dataset"))


def generate_data_yaml(new_dataset_path: str, classes: dict):
    # list dir
    dir_names = [x for x in os.listdir(new_dataset_path) if os.path.isdir(os.path.join(new_dataset_path, x))]
    with open(os.path.join(new_dataset_path, "data.yaml"), "w", encoding="utf-8") as f:

        if len(dir_names) == 0:
            raise Exception(f"No folder found in {new_dataset_path}")
        for dir_name in dir_names:
            if dir_name not in ["train", "val", "test"]:
                continue
            f.write(f"{dir_name}: {dir_name}/images\n")

        f.write("nc: {}\n".format(len(classes)))
        f.write("names:\n")
        for class_id, class_name in classes.items():
            f.write(f"  {class_id}: {class_name}\n")

    print(" > data.yaml generated")


# convert bounding box from yolo format to coco format
def convert_yolo_to_coco_format(yolo_bbox, img_width, img_height):
    """
    Convert bounding box from yolo format to coco format.

    Args:
        yolo_bbox (list): Bounding box in yolo format (x_center_norm, y_center_norm, width_norm, height_norm).
        img_width (int): Image width.
        img_height (int): Image height.

    Returns:
        List containing bounding box in coco format (x_min, y_min, width, height).
    """
    x_center_norm, y_center_norm, width_norm, height_norm = yolo_bbox
    x_min = (x_center_norm - width_norm / 2) * img_width
    y_min = (y_center_norm - height_norm / 2) * img_height
    width = width_norm * img_width
    height = height_norm * img_height

    return [x_min, y_min, width, height]


def process_annotation_file(label_file, labels_path, images_path, idx_to_catname_map, folder):
    """
    Return
    """
    data = []
    ann_id = 0
    img_file = label_file.replace('.txt', '.jpg')  # Assuming image format is .jpg
    img_path = os.path.join(images_path, img_file)

    # Check if corresponding image file exists
    if not os.path.exists(img_path):
        return data

    # Get image dimensions
    with Image.open(img_path) as img:
        img_width, img_height = img.size

    # keep end of path (ex: "datasets/yolo taco-base-gif xxx/train/images/000000000001.jpg" -> "train/images/000000000001.jpg")
    img_path_end = "/".join(img_path.split(os.sep)[-3:])

    # Read YOLO annotations
    with open(os.path.join(labels_path, label_file), 'r', encoding="utf-8") as file:
        for line in file:
            try:
                cat_id, cx, cy, width, height = [float(x) for x in line.split()]
            except Exception as e:
                print(f" > Error with line: {line}")
                continue

            cat_id = int(cat_id)
            cat_name = idx_to_catname_map.get(cat_id, 'Unknown')

            # Compute area
            area = (width * img_width) * (height * img_height)

            data.append(
                [img_path_end, img_file, img_width, img_height, cat_id, cat_name, ann_id, cx, cy, width, height, area,
                 folder])
            ann_id += 1

    return data


def generate_meta_df(root_path: str, catidx_2_catname: dict, n_jobs=-1):
    final_columns = ['path', 'img_file', 'img_width', 'img_height', 'cat_id', 'cat_name', 'ann_id', 'cx', 'cy', 'width',
                     'height', 'area', 'split']
    print(f"> Generating meta_df for {root_path}")

    all_data = []
    for folder in ['train', 'val', 'test']:
        if folder not in os.listdir(root_path):
            continue

        images_path = os.path.join(root_path, folder, 'images')
        labels_path = os.path.join(root_path, folder, 'labels')

        label_files = os.listdir(labels_path)
        results = Parallel(n_jobs=n_jobs)(
            delayed(process_annotation_file)(label_file, labels_path, images_path, catidx_2_catname, folder) for
            label_file in tqdm(label_files, desc=f"Processing {folder} dataset"))

        for result in results:
            all_data.extend(result)

    meta_df = pd.DataFrame(all_data, columns=final_columns)
    print(f"> Done. meta_df shape: {meta_df.shape}")
    #print(meta_df.head())
    return meta_df


def main_data_processing_yolo_format(cat_lang="fr", no_test_set=False, val_size=0.1, test_size=0.1, n_jobs=-1):
    TACO_DATASET_ROOT_PATH = r"N:\My Drive\KESKIA Drive Mlamali\datasets\taco-2gb"
    YYYYMMDDHH = datetime.now().strftime("%Y%m%d_%H")

    taco_meta_df = pd.read_csv(os.path.join(TACO_DATASET_ROOT_PATH, "meta_df.csv"))

    taco_meta_df["path"] = taco_meta_df["img_file"].apply(lambda x: os.path.join(TACO_DATASET_ROOT_PATH, "data", x))

    # add new assets file path (replace '/' by '_')
    taco_meta_df["img_file"] = taco_meta_df["img_file"].apply(lambda x: x.replace("/", "_"))

    # Calcul et ajout des nouvelles colonnes normalisées (cx cy rw rh)
    taco_meta_df['x_center_norm'] = (taco_meta_df['x'] + taco_meta_df['width'] / 2) / taco_meta_df['img_width']
    taco_meta_df['y_center_norm'] = (taco_meta_df['y'] + taco_meta_df['height'] / 2) / taco_meta_df['img_height']
    taco_meta_df['width_norm'] = taco_meta_df['width'] / taco_meta_df['img_width']
    taco_meta_df['height_norm'] = taco_meta_df['height'] / taco_meta_df['img_height']

    # process cat_id
    taco_meta_df["cat_id"] = taco_meta_df["cat_name"].apply(lambda x: EN_CATNAME_2_CATIDX[x])
    print("> taco_meta_df shape: ", taco_meta_df.shape)
    print("> taco_meta_df columns: ", list(taco_meta_df.columns))
    print("-" * 10)
    # --- split dataset
    print(" > Splitting dataset")
    dfs_splitting = split_dataset(taco_meta_df, val_size=val_size, test_size=test_size, random_state=123,
                                  stratify_by="cat_name", no_test_set=no_test_set)

    train_df, val_df, test_df = dfs_splitting if not no_test_set else (dfs_splitting[0], dfs_splitting[1], None)

    for df, df_name in [(train_df, "train"), (val_df, "val"), (test_df, "test")]:
        df["split"] = df_name
        if df is not None:
            print(f" * {df_name} dataset: {len(df)} ({len(df) / len(taco_meta_df) * 100:.1f}%)")
            print(df["cat_name"].value_counts())

    print("-" * 10)
    taco_meta_df = pd.concat([train_df, val_df, test_df], ignore_index=True)

    # --- Processing of the datasets
    print(" > Launching processing of the datasets")
    NEW_TACO_DATASET_PATH = f"{os.path.dirname(TACO_DATASET_ROOT_PATH)}/taco-dataset (yoloformat) train-{len(train_df)}-val-{len(val_df)}"
    NEW_TACO_DATASET_PATH = f"{NEW_TACO_DATASET_PATH}-test-{len(test_df)}" if not no_test_set else NEW_TACO_DATASET_PATH
    NEW_TACO_DATASET_PATH = f"{NEW_TACO_DATASET_PATH} {YYYYMMDDHH}"

    ### plot class distribution (train, val, test, bar on same plot) # grouped bar plot
    # todo make a fonction for this from meta_df save
    fig, ax = plt.subplots(figsize=(20, 10))
    ax = sns.countplot(x="cat_name", hue="split", data=taco_meta_df)
    ax.set_ticks(rotation=90)
    plt.tight_layout()
    plt.savefig(os.path.join(NEW_TACO_DATASET_PATH, "class_distribution.png"))
    plt.close()

    print(f" > New dataset path: {NEW_TACO_DATASET_PATH}")
    for df, df_name in [(train_df, "train"), (val_df, "val"), (test_df, "test")]:
        if df is not None:
            process_images_parallel(df, NEW_TACO_DATASET_PATH, df_name, n_jobs=n_jobs)
    print(f" > Done. New dataset path: {NEW_TACO_DATASET_PATH}")

    #todo : dans le dictionnaire CATIDX_2_EN_CATNAME, prendre juste le 60 premier qd c juste le processing du tacodataset
    generate_data_yaml(NEW_TACO_DATASET_PATH, classes=CATIDX_2_EN_CATNAME if cat_lang == "en" else CATIDX_2_FR_CATNAME)

    # --- Create meta_df.csv
    meta_df = generate_meta_df(NEW_TACO_DATASET_PATH,
                               catidx_2_catname=CATIDX_2_EN_CATNAME if cat_lang == "en" else CATIDX_2_FR_CATNAME)
    print(f" > meta_df shape: {meta_df.shape}")
    meta_df.to_csv(os.path.join(NEW_TACO_DATASET_PATH, f'meta_df.csv'), index=False)


def main_meta_df_generation():
    TACO_DATASET_ROOT_PATH = r"N:\My Drive\KESKIA Drive Mlamali\datasets\taco-yolo-format train-4066-val-718 20231218_14"
    # define the path to your YAML file
    yaml_file_path = os.path.join(TACO_DATASET_ROOT_PATH, "data.yaml")
    if not os.path.exists(yaml_file_path):
        raise Exception(f"YAML file not found at {yaml_file_path}")
    # open the YAML file and load it into a dictionary
    with open(yaml_file_path, 'r', encoding="utf-8") as f:
        data_yaml = yaml.safe_load(f)

    meta_df = generate_meta_df(TACO_DATASET_ROOT_PATH, catidx_2_catname=data_yaml["names"])

    # Save to CSV
    YYYYMMDDHH = datetime.now().strftime("%Y%m%d_%H")
    meta_df.to_csv(os.path.join(TACO_DATASET_ROOT_PATH, f'meta_df.csv'), index=False)


if __name__ == "__main__":
    main_data_processing_yolo_format(cat_lang="fr", no_test_set=0, val_size=0.1, test_size=0.1, n_jobs=4)
